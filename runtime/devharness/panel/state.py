"""Read-only state for the panel: the loop snapshot, the ``→ next`` hint, and the pending question.

Ported verbatim (behaviour-for-behaviour) from the console TUI's read helpers
(``console/tui.py`` ``_q1`` / ``_latest_*`` / ``_plan_outcomes`` / ``_next_hint`` /
``_latest_unanswered_question``), but as pure functions over a caller-supplied READ connection
instead of methods over the TUI's shared connection — so a ``/state`` request opens its own connection
and never contends with the single writer (WAL makes concurrent reads safe). All SELECT-only.

The ``→ next`` hint is the same state machine the TUI surfaces; keeping it identical means the web
Drive pane guides the operator exactly as the TUI does (sign → plan → build → answer → assemble, with
the blocked-task retry command spelled out).
"""

import json
import os
import sqlite3
import time

from devharness.console.state import read_loop_state
from devharness.roles.research import full_question_text, readable_question_text


def _q1(conn: sqlite3.Connection, sql: str, *args):
    row = conn.execute(sql, args).fetchone()
    return row[0] if row else None


def _latest_spec(conn):
    return _q1(conn, "SELECT json_extract(payload,'$.spec_id') FROM events "
                     "WHERE event_type='spec_drafted' ORDER BY seq DESC LIMIT 1")


def _latest_unsigned_spec(conn):
    latest = _latest_spec(conn)
    return latest if latest and latest != read_loop_state(conn).signed_spec_id else None


def latest_correlation(conn):
    """The signed spec's correlation (what D/W act on); else the latest research's correlation."""
    sid = read_loop_state(conn).signed_spec_id
    if sid:
        cid = _q1(conn, "SELECT correlation_id FROM artifacts WHERE artifact_id=?", sid)
        if cid:
            return cid
    return _q1(conn, "SELECT correlation_id FROM events WHERE event_type='research_started' "
                     "ORDER BY seq DESC LIMIT 1")


def _question_correlation(conn):
    """The correlation whose questions A answers: the latest research run while IN FLIGHT (started, no
    spec drafted yet), else the signed-spec correlation (rev 0.3.69 fix — a second research run's
    interview must win over the signed-spec preference, but an abandoned run's orphan question must not
    hijack the hint once its spec drafts)."""
    rcid = _q1(conn, "SELECT correlation_id FROM events WHERE event_type='research_started' "
                     "ORDER BY seq DESC LIMIT 1")
    if rcid and not _q1(conn, "SELECT artifact_id FROM artifacts WHERE artifact_type='spec' "
                              "AND correlation_id=? LIMIT 1", rcid):
        return rcid
    return latest_correlation(conn)


def latest_unanswered_question(conn):
    cid = _question_correlation(conn)
    if not cid:
        return None
    asked = [r[0] for r in conn.execute(
        "SELECT json_extract(payload,'$.question_id') FROM events "
        "WHERE event_type='question_asked' AND correlation_id=? ORDER BY seq", (cid,))]
    answered = {r[0] for r in conn.execute(
        "SELECT json_extract(payload,'$.question_id') FROM events "
        "WHERE event_type='question_answered' AND correlation_id=?", (cid,))}
    pending = [q for q in asked if q not in answered]
    return pending[-1] if pending else None


def _pending_question_text(conn, question_id):
    """Raw question_text for a pending id — restart-proof direct read; latest row wins (a re-driven
    run resets its round counter so ids can collide across runs against one correlation)."""
    return _q1(conn,
               "SELECT json_extract(payload,'$.question_text') FROM events "
               "WHERE event_type='question_asked' AND correlation_id=? "
               "AND json_extract(payload,'$.question_id')=? ORDER BY seq DESC LIMIT 1",
               _question_correlation(conn), question_id)


def pending_question(conn) -> dict | None:
    """{'question_id', 'text', 'readable', 'display'} for the pending research question, else None.
    The Research pane renders ``display`` (the COMPLETE question, readable — rev 0.4.12: ``text``
    is the raw elicit JSON for a divergence round, a machine wall on the card), the Drive hint
    uses ``readable`` (one-liner), and ``text`` stays the raw stored value (API compat)."""
    qid = latest_unanswered_question(conn)
    if not qid:
        return None
    text = _pending_question_text(conn, qid) or ""
    return {"question_id": qid, "text": text,
            "display": full_question_text(text) if text else "",
            "readable": readable_question_text(text, max_len=400) if text else ""}


def _plan_records(conn):
    """(plan task dicts from the artifact, {task_id: latest_outcome}); None when there is no plan."""
    cid = latest_correlation(conn)
    pid = _q1(conn, "SELECT json_extract(payload,'$.plan_id') FROM events "
                    "WHERE event_type='plan_drafted' AND correlation_id=? ORDER BY seq DESC LIMIT 1",
              cid) if cid else None
    if not pid:
        return None
    row = conn.execute("SELECT payload_json FROM artifacts WHERE artifact_id=?", (pid,)).fetchone()
    if not row:
        return None
    tasks = json.loads(row[0]).get("tasks", [])
    task_ids = [t.get("task_id") for t in tasks]
    latest = {}
    for tid, outcome in conn.execute(
            "SELECT json_extract(payload,'$.task_id'), json_extract(payload,'$.outcome') "
            "FROM events WHERE event_type='terminal_outcome' ORDER BY seq"):
        if tid in task_ids:
            latest[tid] = outcome
    return tasks, latest


def _plan_outcomes(conn):
    """(task_ids, {task_id: latest_outcome}) for the current plan; None when there is no plan yet."""
    records = _plan_records(conn)
    if records is None:
        return None
    tasks, latest = records
    return [t.get("task_id") for t in tasks], latest


def _certifiable(conn, task_id) -> bool:
    """Mirror of ``ConsoleReview.certify``'s refusal preconditions — True only when a certify POST
    would be admitted: started, lifecycle non-terminal, verifier pass in the current attempt."""
    from devharness.task_lifecycle.base import TerminalStates
    from devharness.task_lifecycle.done_is_earned import _attempt_start_seq, _has_verifier_pass

    if _q1(conn, "SELECT 1 FROM proj_task_started WHERE task_id=?", task_id) is None:
        return False
    state = _q1(conn, "SELECT current_state FROM proj_task_lifecycle WHERE task_id=?", task_id)
    if state in TerminalStates:
        return False
    return _has_verifier_pass(conn, task_id, _attempt_start_seq(conn, task_id))


def plan_tasks(conn, *, busy: bool) -> list[dict] | None:
    """Ordered task rows for the Drive pane; None when there is no plan yet.

    Each row: task_id, description (trunc), outcome (None = no terminal), reason (blocked rows),
    buildable (pending AND every declared dependency completed — an out-of-order explicit dispatch
    builds against a tree missing its dependencies' code, so the button is withheld), certifiable
    (the certify preconditions hold; computed only when idle — mid-dispatch it flickers true while
    the loop itself is about to certify)."""
    records = _plan_records(conn)
    if records is None:
        return None
    tasks, latest = records
    rows = []
    for t in tasks:
        tid = t.get("task_id")
        outcome = latest.get(tid)
        desc = (t.get("description") or "").strip()
        row = {"task_id": tid, "outcome": outcome,
               "description": desc[:80] + ("…" if len(desc) > 80 else "")}
        if outcome is None:
            deps = t.get("dependencies") or []
            row["buildable"] = all(latest.get(d) == "completed" for d in deps)
            row["certifiable"] = False if busy else _certifiable(conn, tid)
        elif outcome != "completed":
            reason = _terminal_reason(conn, tid)
            row["reason"] = reason[:120] + ("…" if len(reason) > 120 else "")
        rows.append(row)
    return rows


def _terminal_reason(conn, task_id):
    return _q1(conn,
               "SELECT COALESCE(NULLIF(json_extract(payload,'$.reason'), ''), "
               "json_extract(payload,'$.detail')) FROM events "
               "WHERE event_type='terminal_outcome' AND json_extract(payload,'$.task_id')=? "
               "ORDER BY seq DESC LIMIT 1", task_id) or ""


def next_hint(conn, *, target_path: str | None, busy_label: str | None) -> str:
    """The ``→ next`` hint — the console's state machine, verbatim (``tui.py`` ``_next_hint``)."""
    return _hint_and_action(conn, target_path=target_path, busy_label=busy_label)[0]


def _hint_and_action(conn, *, target_path: str | None, busy_label: str | None) -> tuple[str, str]:
    """(hint text, machine token) — the token lets the UI highlight/gate the matching button.

    Tokens: busy · answer · sign · research · plan · retry · target · build · assemble · done.
    ``answer`` wins over ``busy`` when research parks on a question (the one state where a POST is
    live while a step runs — greying everything out there reads as stuck, the rev-0.3.74 class)."""
    if busy_label:
        if busy_label == "research":
            qid = latest_unanswered_question(conn)
            if qid:
                text = _pending_question_text(conn, qid)
                q = readable_question_text(text, max_len=120) if text else "the research question"
                return f"answer (research is waiting): {q}", "answer"
        return f"running: {busy_label}  (cancel to abandon)", "busy"
    qid = latest_unanswered_question(conn)
    if qid:
        text = _pending_question_text(conn, qid)
        if text:
            return f"answer: {readable_question_text(text, max_len=150)}", "answer"
        return "answer the research question", "answer"
    if _latest_unsigned_spec(conn):
        return "sign the drafted spec", "sign"
    if not read_loop_state(conn).spec_signed:
        return "set a build target, then start research", "research"
    outcomes = _plan_outcomes(conn)
    if outcomes is None:
        return "plan the signed spec", "plan"
    task_ids, latest = outcomes
    blocked = [t for t in task_ids if latest.get(t) not in (None, "completed")]
    pending = [t for t in task_ids if t not in latest]
    if blocked:
        tid, outcome = blocked[0], latest[blocked[0]]
        reason = _terminal_reason(conn, tid)
        if len(reason) > 120:
            reason = reason[:120] + "…"
        note = f" ({reason})" if reason else ""
        cid = latest_correlation(conn)
        retry = f"dispatch with correlation={cid} task={tid}"
        if pending:
            return (f"⚠ {tid} {outcome}{note} — needs review; build SKIPS PAST it to the next pending "
                    f"task ({len(pending)} left) — {retry} to retry it explicitly"), "retry"
        return (f"⚠ {tid} {outcome}{note} — assemble blocked until every task completes; "
                f"{retry} to retry"), "retry"
    if pending:
        if target_path is None and not os.environ.get("DEVHARNESS_TARGET_REPO"):
            return f"set a build target, then build  ({len(pending)} tasks)", "target"
        return f"build the next task  ({len(pending)} left)", "build"
    if _q1(conn, "SELECT 1 FROM events WHERE event_type='project_assembled' AND correlation_id=?",
           latest_correlation(conn)):
        return "done — project assembled (all tasks built + merged)", "done"
    return "assemble the project (merge into the target's main)", "assemble"


def last_activity_millis(conn, *, now_millis=None) -> int | None:
    """The newest ``*_at_millis`` among the store's last 20 events — when real work last happened.

    File mtime is NOT that signal: merely opening/closing a WAL store checkpoints and bumps the
    mtime with zero events written, which laundered a stale store's age minutes after the mtime
    heuristic shipped (rev 0.4.5). Events have no timestamp column; payloads carry ``*_at_millis``
    by convention — the newest across the last 20 is robust to the few types that carry none.
    FUTURE-dated values are ignored (60s clock slack): a trust grant's ``expires_at_millis``
    (granted + 7 days) is a schedule, not activity — counting it would crown a dead store the
    "most recently active" for a week after any promotion (review catch, same wrong-store class).
    None = no events (or none carrying a past timestamp): callers fall back to mtime."""
    horizon = (now_millis or int(time.time() * 1000)) + 60_000
    best = None
    for (p,) in conn.execute("SELECT payload FROM events ORDER BY seq DESC LIMIT 20"):
        try:
            d = json.loads(p) if p else {}
        except ValueError:
            continue
        if isinstance(d, dict):
            for k, v in d.items():
                if k.endswith("_at_millis") and isinstance(v, (int, float)) and 0 < v <= horizon:
                    best = max(best or 0, int(v))
    return best


def grand_total_cost(conn) -> float:
    return _q1(conn, "SELECT SUM(spent_usd) FROM proj_cost") or 0.0


def invariant_violation_count(conn) -> int:
    """How many invariant_violated events the live monitor has emitted (rev 0.3.87)."""
    return _q1(conn, "SELECT COUNT(*) FROM events WHERE event_type='invariant_violated'") or 0


def snapshot(conn, *, target_path, test_command, busy_label, busy_job) -> dict:
    """The full /state payload the Drive pane renders."""
    st = read_loop_state(conn)
    pq = pending_question(conn)
    hint, action = _hint_and_action(conn, target_path=target_path, busy_label=busy_label)
    return {
        "active_role": st.active_role,
        "spec_signed": st.spec_signed,
        "signed_spec_id": st.signed_spec_id,
        "signed_by": st.signed_by,
        "unsigned_spec_id": _latest_unsigned_spec(conn),
        "tasks_by_state": st.tasks_by_state,
        "tasks": plan_tasks(conn, busy=busy_label is not None),
        "event_count": st.event_count,
        "correlation_id": latest_correlation(conn),
        "next_hint": hint,
        "next_action": action,
        "busy": busy_label,
        "busy_job": busy_job,
        "pending_question": pq,
        "target_path": target_path,
        "test_command": test_command,
        "cost_total_usd": round(grand_total_cost(conn), 4),
        "invariant_violations": invariant_violation_count(conn),
    }
