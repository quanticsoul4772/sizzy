"""Done-is-earned enforcement (B2.6, Invariant 5, §S3).

A `completed` terminal requires BOTH (a) a verifier_outcome with passed=True AND
(b) a reviewer_certified — separately. `complete` refuses otherwise (DoneNotEarned).
"""

import json


class DoneNotEarned(RuntimeError):
    """Raised when completing a task that lacks a verifier pass and/or reviewer certification."""


def _task_events(conn, event_type, task_id, min_seq=-1):
    for seq, payload in conn.execute(
        "SELECT seq, payload FROM events WHERE event_type = ? AND seq > ?", (event_type, min_seq)
    ):
        record = json.loads(payload)
        if record.get("task_id") == task_id:
            yield record


def _attempt_start_seq(conn, task_id) -> int:
    """The seq of the most recent ``task_started`` for this task — the start of the CURRENT attempt.

    The developer emits ``task_started`` at the start of every run, so each attempt (including a re-drive)
    opens with a fresh, higher-seq marker. Scoping the earned-twice evidence to events after this boundary
    keeps Invariant 5 sound across re-drives: a verifier pass from an earlier abandoned/rejected attempt
    (seq below this marker) cannot be combined with the current attempt's reviewer certification. The
    single-writer lock serialises attempts, so the boundary is unambiguous. Returns -1 if no task_started
    is recorded (no scoping — back-compat for callers/tests that emit evidence without a start marker)."""
    best = -1
    for seq, payload in conn.execute("SELECT seq, payload FROM events WHERE event_type = 'task_started'"):
        if json.loads(payload).get("task_id") == task_id and seq > best:
            best = seq
    return best


def _has_verifier_pass(conn, task_id, min_seq=-1) -> bool:
    return any(r.get("passed") for r in _task_events(conn, "verifier_outcome", task_id, min_seq))


def _has_verifier_fail(conn, task_id, min_seq=-1) -> bool:
    return any(not r.get("passed") for r in _task_events(conn, "verifier_outcome", task_id, min_seq))


def _has_reviewer_certified(conn, task_id, min_seq=-1) -> bool:
    return any(True for _ in _task_events(conn, "reviewer_certified", task_id, min_seq))


def _has_reviewer_rejected(conn, task_id, min_seq=-1) -> bool:
    return any(True for _ in _task_events(conn, "reviewer_rejected", task_id, min_seq))


def can_complete(task_id, conn) -> bool:
    """True iff a verifier pass AND a reviewer certification BOTH exist in the CURRENT attempt (after the
    most recent task_started) — so a re-driven task cannot earn 'done twice' by mixing an earlier attempt's
    verifier pass with this attempt's reviewer certification (Invariant 5)."""
    since = _attempt_start_seq(conn, task_id)
    return _has_verifier_pass(conn, task_id, since) and _has_reviewer_certified(conn, task_id, since)


def complete(task_id, lifecycle, conn, event_bus, *, now_millis=None) -> None:
    if not can_complete(task_id, conn):
        since = _attempt_start_seq(conn, task_id)  # report the CURRENT-attempt evidence (Inv 5)
        raise DoneNotEarned(
            f"task {task_id} cannot complete: needs a verifier pass AND a reviewer certification in the "
            f"current attempt (verifier_pass={_has_verifier_pass(conn, task_id, since)}, "
            f"reviewer_cert={_has_reviewer_certified(conn, task_id, since)})"
        )
    lifecycle.transition(task_id, lifecycle.state(task_id), "completed", event_bus, conn, now_millis=now_millis)


def reject(task_id, reason, lifecycle, conn, event_bus, *, now_millis=None) -> None:
    lifecycle.transition(task_id, lifecycle.state(task_id), "rejected", event_bus, conn, reason=reason, now_millis=now_millis)


def abort(task_id, reason, lifecycle, conn, event_bus, *, now_millis=None) -> None:
    lifecycle.transition(task_id, lifecycle.state(task_id), "aborted", event_bus, conn, reason=reason, now_millis=now_millis)
