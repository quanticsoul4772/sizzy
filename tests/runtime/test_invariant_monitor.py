"""Live invariant monitor: the behavioral checks + the sweep (emit invariant_violated, dedup, no feedback
loop). The headline case is the #4 regression — a task_started with no terminal_outcome (rev 0.3.87)."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cli._bus import projected_bus
from devharness.migrate import migrate
from devharness.monitor import checks
from devharness.monitor.sweep import run_invariant_sweep


def _store():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn, projected_bus(conn)


def _iv(conn):
    return [json.loads(p) for (p,) in conn.execute(
        "SELECT payload FROM events WHERE event_type='invariant_violated' ORDER BY seq")]


def _started(bus, tid, corr="c"):
    bus.emit_sync("task_started",
                  {"task_id": tid, "role": "developer", "worktree_path": "/w",
                   "correlation_id": corr, "started_at_millis": 1}, correlation_id=corr)


def _terminal(bus, tid, outcome="completed", corr="c"):
    bus.emit_sync("terminal_outcome",
                  {"task_id": tid, "outcome": outcome, "detail": "", "reason": "",
                   "correlation_id": corr, "terminated_at_millis": 2}, correlation_id=corr)


def _earn(bus, tid, corr="c"):
    bus.emit_sync("verifier_outcome",
                  {"task_id": tid, "verifier": "v", "passed": True, "detail": "", "evidence": ""},
                  correlation_id=corr)
    bus.emit_sync("reviewer_certified",
                  {"task_id": tid, "reviewer_session_id": "r", "evidence": "",
                   "correlation_id": corr, "certified_at_millis": 2}, correlation_id=corr)


# --- the headline: #4 silent-loop regression ---

def test_orphan_task_started_without_terminal_is_flagged_inv10():
    conn, bus = _store()
    _started(bus, "t1")  # crashed dispatch analog: started, never terminated
    new = run_invariant_sweep(conn, bus, now_millis=5)
    assert [v.invariant_number for v in new] == [10]
    ivs = _iv(conn)
    assert len(ivs) == 1 and ivs[0]["invariant_number"] == 10 and ivs[0]["task_id"] == "t1"


def test_orphan_skipped_while_the_write_lock_is_held():
    """The liveness half must NOT fire while a build is legitimately in flight (lock held)."""
    conn, bus = _store()
    bus.emit_sync("write_lock_acquired",
                  {"lock_token": "tok", "holder_role": "developer", "correlation_id": "c",
                   "acquired_at_millis": 1}, correlation_id="c")
    _started(bus, "t1")  # in-flight, not yet terminated — lock held, so not an orphan
    new = run_invariant_sweep(conn, bus)
    assert not any(v.invariant_number == 10 for v in new)


# --- the other behavioral checks ---

def test_double_terminal_is_flagged_inv10():
    conn, bus = _store()
    _started(bus, "t1")
    _terminal(bus, "t1", "completed")
    _terminal(bus, "t1", "aborted")  # a second terminal for the same task
    new = run_invariant_sweep(conn, bus)
    assert any(v.invariant_number == 10 and "more than one" in v.property for v in new)


def test_completed_without_earning_is_flagged_inv5():
    conn, bus = _store()
    _started(bus, "t1")
    _terminal(bus, "t1", "completed")  # no verifier pass / reviewer cert
    new = run_invariant_sweep(conn, bus)
    assert any(v.invariant_number == 5 for v in new)


def test_concurrent_write_lock_is_flagged_inv1():
    conn, bus = _store()
    bus.emit_sync("write_lock_acquired",
                  {"lock_token": "tok1", "holder_role": "developer", "correlation_id": "c",
                   "acquired_at_millis": 1}, correlation_id="c")
    bus.emit_sync("write_lock_acquired",
                  {"lock_token": "tok2", "holder_role": "developer", "correlation_id": "c",
                   "acquired_at_millis": 2}, correlation_id="c")  # a second holder before release
    new = run_invariant_sweep(conn, bus)
    assert any(v.invariant_number == 1 for v in new)


def test_empty_correlation_id_is_flagged_inv9():
    conn, _bus = _store()
    # emit_sync refuses an empty correlation_id, so simulate a direct-SQL tamper
    conn.execute("INSERT INTO events (event_id, correlation_id, event_type, payload, prev_hash, hash) "
                 "VALUES ('x', '', 'role_transitioned', '{}', '', '')")
    conn.commit()
    assert any(v.invariant_number == 9 for v in checks.check_correlation_coverage(conn))


# --- re-drive awareness (rev 0.3.93): the harness legitimately re-terminates + re-starts a task ---

def test_redrive_is_not_flagged_inv10():
    """The hinge: a task_started RESETS terminal-in-window, so start,term,start,term (an operator re-drive
    of a rejected task) is clean — NOT a double-terminal."""
    conn, bus = _store()
    _started(bus, "t1"); _terminal(bus, "t1", "rejected")   # attempt 1
    _started(bus, "t1"); _earn(bus, "t1"); _terminal(bus, "t1", "completed")  # attempt 2 (re-drive)
    assert run_invariant_sweep(conn, bus) == []


def test_non_terminal_retry_shape_is_not_flagged():
    """The bounded auto-retry / transient_sdk_glitch shape start,start,...,completed (a non-terminal rewind
    then the real terminal) is clean at the monitor level — the fault-injection oracle depends on this."""
    conn, bus = _store()
    _started(bus, "t1"); _started(bus, "t1")   # attempt rewound non-terminally, re-started
    _earn(bus, "t1"); _terminal(bus, "t1", "completed")
    assert run_invariant_sweep(conn, bus) == []


def test_abort_of_never_started_is_not_flagged_inv10():
    """The rev-0.3.86 crash->abort path emits a terminal with no preceding task_started; the following
    real attempt (start,completed) is fine — aborted,start,completed is clean."""
    conn, bus = _store()
    _terminal(bus, "t1", "aborted")            # abort with no preceding start
    _started(bus, "t1"); _earn(bus, "t1"); _terminal(bus, "t1", "completed")
    assert run_invariant_sweep(conn, bus) == []


def test_redriven_then_orphaned_trailing_attempt_is_flagged_inv10():
    """The new true-positive: a re-driven task whose LATEST attempt orphaned (started, no terminal). The
    old check missed it because the task_id appeared in an earlier terminal."""
    conn, bus = _store()
    _started(bus, "t1"); _terminal(bus, "t1", "rejected")   # attempt 1 terminated
    _started(bus, "t1")                                     # attempt 2 orphaned (no terminal)
    new = run_invariant_sweep(conn, bus, now_millis=5)
    assert any(v.invariant_number == 10 and "never emitted" in v.property for v in new)


def test_double_completed_after_a_redrive_is_still_flagged_inv10():
    """A genuine double within one attempt still flags even after a legit re-drive."""
    conn, bus = _store()
    _started(bus, "t1"); _terminal(bus, "t1", "rejected")   # re-drive
    _started(bus, "t1"); _earn(bus, "t1")
    _terminal(bus, "t1", "completed"); _terminal(bus, "t1", "completed")  # two terminals, one attempt
    new = run_invariant_sweep(conn, bus)
    assert any(v.invariant_number == 10 and "more than one" in v.property for v in new)


def test_completed_earned_in_its_own_attempt_not_flagged_even_if_a_later_attempt_failed_inv5():
    """The pgharness-val2 false-positive: a completed earned in attempt 2 must NOT be flagged just because
    a later attempt 3 failed (the old global can_complete read the latest attempt)."""
    conn, bus = _store()
    _started(bus, "t1"); _terminal(bus, "t1", "rejected")           # attempt 1: not earned
    _started(bus, "t1"); _earn(bus, "t1"); _terminal(bus, "t1", "completed")  # attempt 2: earned
    _started(bus, "t1"); _terminal(bus, "t1", "rejected")           # attempt 3: not earned
    new = run_invariant_sweep(conn, bus)
    assert not any(v.invariant_number == 5 for v in new)


def test_completed_with_no_preceding_task_started_uses_log_start_fallback_inv5():
    """A completed with no preceding task_started scans the whole log for the earning (can_complete's
    back-compat) — so an earned-but-startless completed is not false-flagged."""
    conn, bus = _store()
    _earn(bus, "t1")                       # verifier pass + reviewer cert, no task_started
    _terminal(bus, "t1", "completed")
    assert not any(v.invariant_number == 5 for v in run_invariant_sweep(conn, bus))


def test_null_task_id_events_produce_no_phantom_violation():
    """A task_started with no task_id in its payload can't be attributed to an attempt — skipped, not a
    phantom orphan/double."""
    conn, _bus = _store()
    conn.execute("INSERT INTO events (event_id, correlation_id, event_type, payload, prev_hash, hash) "
                 "VALUES ('a', 'c', 'task_started', '{}', '', '')")
    conn.commit()
    assert not any(v.invariant_number == 10 for v in checks.check_terminal_per_task(conn))


# --- the sweep: dedup + clean log ---

def test_clean_completed_build_has_no_violations():
    conn, bus = _store()
    _started(bus, "t1")
    _earn(bus, "t1")            # verifier pass + reviewer cert after task_started
    _terminal(bus, "t1", "completed")
    assert run_invariant_sweep(conn, bus) == []
    assert _iv(conn) == []


def test_sweep_is_idempotent_dedups_a_repeated_violation():
    conn, bus = _store()
    _started(bus, "t1")  # orphan
    first = run_invariant_sweep(conn, bus, now_millis=5)
    second = run_invariant_sweep(conn, bus, now_millis=6)  # nothing changed
    assert len(first) == 1 and second == []
    assert len(_iv(conn)) == 1  # exactly one invariant_violated, not one per sweep


def test_monitor_ignores_its_own_events_no_feedback_loop():
    conn, bus = _store()
    _started(bus, "t1")
    run_invariant_sweep(conn, bus)              # emits an invariant_violated
    # a third sweep still emits nothing new and the invariant_violated event triggers no check
    assert run_invariant_sweep(conn, bus) == []
    assert len(_iv(conn)) == 1
