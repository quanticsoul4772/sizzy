"""The behaviorally-checkable invariant checks — each ``(conn) -> list[Violation]``, reusing the existing
canonical helper so the monitor composes rather than reinvents.

Only the 7 invariants decidable from the event log are here (1, 5, 7, 9, 10, 12, 17). The structural ones
(2/3 tool-inventory, 6 schema, 8 rebuild-parity, 11 struct-field, 13 AST, 14/15/18 registry) are not
stream-checkable and stay test-only.
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field

from devharness.events.bus import IntegrityError, verify_chain
from devharness.retro.gate_change_validator import would_weaken_core_gate

_WEAKENING = ("loosen", "remove_signature")


@dataclass(frozen=True)
class Violation:
    invariant_number: int
    property: str
    detail: str = ""
    task_id: str = ""
    correlation_id: str = ""
    offending_event_ids: list = field(default_factory=list)


def _rows(conn, event_type):
    """(event_id, payload_dict, correlation_id) for each event of a type, in seq order."""
    for eid, payload, corr in conn.execute(
        "SELECT event_id, payload, correlation_id FROM events WHERE event_type = ? ORDER BY seq",
        (event_type,),
    ):
        yield eid, json.loads(payload), corr


def check_single_writer(conn) -> list:
    """Inv 1: at most one write-lock holder — a second ``write_lock_acquired`` before the held token's
    ``write_lock_released`` is a concurrent writer."""
    viols, held_token, held_event = [], None, None
    for et, eid, payload in conn.execute(
        "SELECT event_type, event_id, payload FROM events "
        "WHERE event_type IN ('write_lock_acquired', 'write_lock_released') ORDER BY seq"
    ):
        d = json.loads(payload)
        tok = d.get("lock_token")
        if et == "write_lock_acquired":
            if held_token is not None:
                viols.append(Violation(
                    1, "single writer: two write locks held at once", f"lock {held_token} still held",
                    correlation_id=d.get("correlation_id", ""), offending_event_ids=[held_event, eid]))
            held_token, held_event = tok, eid
        elif tok == held_token:
            held_token, held_event = None, None
    return viols


def check_done_earned(conn) -> list:
    """Inv 5: a ``completed`` terminal must be earned in ITS OWN attempt — a verifier pass AND a reviewer
    cert between the completed terminal's immediately-preceding ``task_started`` and the terminal itself.

    A re-driven ``task_id`` legitimately has multiple attempts; scoping to the attempt window (rather than
    the global ``can_complete``, which reads the LATEST attempt's start) avoids false-flagging an earlier
    legitimate completion when a LATER attempt failed. Fallback: no preceding ``task_started`` → lower bound
    -1 (whole log up to the terminal), matching ``can_complete``'s back-compat behaviour."""
    viols = []
    for term_seq, eid, payload, corr in conn.execute(
        "SELECT seq, event_id, payload, correlation_id FROM events "
        "WHERE event_type = 'terminal_outcome' ORDER BY seq"
    ):
        d = json.loads(payload)
        if d.get("outcome") != "completed":
            continue
        tid = d.get("task_id")
        row = conn.execute(
            "SELECT MAX(seq) FROM events WHERE event_type = 'task_started' "
            "AND json_extract(payload, '$.task_id') = ? AND seq < ?", (tid, term_seq)).fetchone()
        lo = row[0] if row and row[0] is not None else -1  # exclusive lower bound of the attempt window
        passed = conn.execute(
            "SELECT 1 FROM events WHERE event_type = 'verifier_outcome' "
            "AND json_extract(payload, '$.task_id') = ? AND json_extract(payload, '$.passed') = 1 "
            "AND seq > ? AND seq < ? LIMIT 1", (tid, lo, term_seq)).fetchone()
        certified = conn.execute(
            "SELECT 1 FROM events WHERE event_type = 'reviewer_certified' "
            "AND json_extract(payload, '$.task_id') = ? AND seq > ? AND seq < ? LIMIT 1",
            (tid, lo, term_seq)).fetchone()
        if not (passed and certified):
            viols.append(Violation(
                5, "completed must be earned twice (verifier pass + reviewer cert)",
                "no verifier pass and/or reviewer cert in the attempt",
                task_id=tid or "", correlation_id=corr, offending_event_ids=[eid]))
    return viols


def check_hash_chain(conn) -> list:
    """Inv 7: the event log is append-only + hash-chained; any tamper breaks the recomputed chain."""
    try:
        verify_chain(conn)
        return []
    except IntegrityError as exc:
        return [Violation(7, "event log hash chain broken (tamper/reorder)", str(exc), correlation_id="monitor")]


def check_correlation_coverage(conn) -> list:
    """Inv 9: every event carries a non-empty correlation_id."""
    return [
        Violation(9, "every event must carry a non-empty correlation_id", "empty correlation_id",
                  offending_event_ids=[eid])
        for (eid,) in conn.execute(
            "SELECT event_id FROM events WHERE correlation_id IS NULL OR correlation_id = ''")
    ]


def _lock_held(conn) -> bool:
    """True while a build actively holds the single write lock — the non-circular quiescence signal.
    (A #4-style crashed dispatch RELEASES the lock in its finally, so its orphaned task is still
    catchable; a legitimately in-flight build holds it, so the orphan check is skipped.)"""
    return conn.execute("SELECT 1 FROM proj_lock LIMIT 1").fetchone() is not None


def check_terminal_per_task(conn, *, include_orphans=True) -> list:
    """Inv 10: every started ATTEMPT emits exactly one terminal.

    A ``task_id`` legitimately gets MULTIPLE terminals + ``task_started``s: the operator re-drives a
    rejected task (the retro dedup is keyed on ``(task_id, terminal_kind)`` because of it) and the bounded
    auto-retry re-runs within a dispatch. So the check is per-ATTEMPT via a seq-ordered walk, NOT per-task_id
    counting. Walk each task's ``task_started`` + ``terminal_outcome`` in seq order: a ``task_started`` opens
    an attempt and **RESETS ``tiw``** (terminal-in-window) — that reset is the hinge that keeps a re-drive
    (start,term,start,term) clean while a genuine double (start,term,term) flags. A 2nd terminal with ``tiw``
    already set is a double-terminal (safety, always runs). A trailing OPEN attempt (started, no following
    terminal) is an orphan (liveness — gated on ``include_orphans``, so an in-flight re-drive whose newest
    attempt is still running under the held lock is not mistaken for a silent termination)."""
    viols = []
    per_task = defaultdict(list)  # task_id -> [(event_type, event_id, corr), ...] in seq order
    for et, eid, payload, corr in conn.execute(
        "SELECT event_type, event_id, payload, correlation_id FROM events "
        "WHERE event_type IN ('task_started', 'terminal_outcome') ORDER BY seq"
    ):
        tid = json.loads(payload).get("task_id")
        if tid is None:  # defensive: a null task_id can't be attributed to an attempt
            continue
        per_task[tid].append((et, eid, corr))
    for tid, evs in per_task.items():
        tiw = False           # a terminal already emitted since the last task_started
        open_start = None     # (event_id, corr) of the current open attempt, or None once terminated
        for et, eid, corr in evs:
            if et == "task_started":
                tiw, open_start = False, (eid, corr)
            else:  # terminal_outcome
                if tiw:  # a 2nd terminal with no start between = genuine double-terminal
                    viols.append(Violation(
                        10, "a task emitted more than one terminal_outcome", "two terminals in one attempt",
                        task_id=tid, correlation_id=corr, offending_event_ids=[eid]))
                tiw, open_start = True, None
        if include_orphans and open_start is not None:  # a trailing started attempt with no terminal
            viols.append(Violation(
                10, "a started task never emitted a terminal_outcome (silent termination)",
                "orphaned: task_started with no terminal", task_id=tid,
                correlation_id=open_start[1], offending_event_ids=[open_start[0]]))
    return viols


def check_core_gates(conn) -> list:
    """Inv 12: a retro proposal can't weaken a core gate — an ENACTED core-gate loosen/remove is a
    hard breach (a weakening candidate should have been auto-rejected before enactment)."""
    return [
        Violation(12, "a core gate was weakened", f"{d.get('target_gate')} {d.get('change_kind')} enacted",
                  correlation_id=corr, offending_event_ids=[eid])
        for eid, d, corr in _rows(conn, "gate_change_enacted")
        if would_weaken_core_gate(d.get("target_gate", ""), d.get("change_kind", ""))
    ]


def check_trusted_memory(conn) -> list:
    """Inv 17: a cross-project (imported) memory entry can't be trusted without a ``memory_entry_verified``
    naming its verifier — a trusted imported entry with no verification event is a breach."""
    verified = {d.get("entry_id") for _e, d, _c in _rows(conn, "memory_entry_verified")}
    viols = []
    for eid, d, corr in _rows(conn, "memory_entry_created"):
        entry_id, src = d.get("entry_id"), d.get("source_project") or ""
        # only imported entries (a foreign source_project) are gated by Inv 17
        if src and src not in ("", "local") and entry_id and entry_id not in verified:
            # trusted iff proj_memory carries it as trusted; if there is no proj_memory, treat as untrusted
            try:
                row = conn.execute(
                    "SELECT 1 FROM proj_memory WHERE entry_id = ? AND trust = 'trusted'", (entry_id,)
                ).fetchone()
            except Exception:  # noqa: BLE001 — no proj_memory / different schema: nothing to flag
                row = None
            if row is not None:
                viols.append(Violation(
                    17, "trusted cross-project memory must carry a verification event",
                    f"entry {entry_id} (from {src}) trusted with no memory_entry_verified",
                    correlation_id=corr, offending_event_ids=[eid]))
    return viols


def all_violations(conn, *, include_orphans=True) -> list:
    """Every behavioral check, in invariant order. ``include_orphans`` gates the Inv-10 liveness half."""
    orphans = include_orphans and not _lock_held(conn)
    return [
        *check_single_writer(conn),
        *check_done_earned(conn),
        *check_hash_chain(conn),
        *check_correlation_coverage(conn),
        *check_terminal_per_task(conn, include_orphans=orphans),
        *check_core_gates(conn),
        *check_trusted_memory(conn),
    ]
