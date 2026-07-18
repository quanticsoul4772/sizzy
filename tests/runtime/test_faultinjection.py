"""Loop fault-injection (feature B, spec rev 0.3.88).

Each probe injects a real failure class (mid-dispatch crash, git-128 checkpoint, hard/transient SDK
error, missing test runner, worktree collision) into a HERMETIC build and the live invariant monitor
judges whether the harness coped. A ``handled`` outcome (one clean terminal, no ``invariant_violated``)
is the positive proof that the rev-0.3.86 fixes hold; a ``regression`` (a silent orphan → Inv 10) is
what a future break looks like.

These are real builds — real ``git init`` + worktree + a verifier subprocess — so they are slower than
the microsecond gate probes; that cost is intrinsic to exercising the whole loop.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console.app import ConsoleApp
from devharness.faultinjection.hermetic import clean_write_hook, hermetic_build, noop_query, FakeParallax, TEST_CMD
from devharness.faultinjection.probes import PROBES
from devharness.faultinjection.runner import run_all_loop_faults, run_loop_fault
from devharness.faultinjection.scheduler import LoopFaultScheduler


def _live():
    """A separate in-memory store to receive the RESULT events (the operator's real log)."""
    return ConsoleApp(db_path=":memory:").connect()


def _count(conn, event_type):
    return conn.execute("SELECT COUNT(*) FROM events WHERE event_type = ?", (event_type,)).fetchone()[0]


def test_hermetic_build_dispatches_cleanly():
    """The scaffold itself is a valid, dispatchable build: a clean run completes with no violation."""
    build = hermetic_build()
    try:
        dev_kwargs = {"base_path": str(build.repo), "base_ref": "feature-base",
                      "query_fn": noop_query(), "write_hook": clean_write_hook}
        terminal = build.developer(test_command=TEST_CMD).dispatch(
            build.correlation_id, parallax=FakeParallax(),
            developer_kwargs=dev_kwargs, snapshot=False, spec_claim_retries=0,
        )
        assert terminal.outcome == "completed"
        assert _count(build.conn, "invariant_violated") == 0
    finally:
        build.cleanup()


@pytest.mark.parametrize("probe_name", list(PROBES.keys()))
def test_each_probe_is_handled(probe_name):
    """Every injected fault is handled: one clean terminal, no fault-handling regression. This is the
    live proof the rev-0.3.86 crash→abort / identity-fallback / transient-retry fixes hold."""
    live = _live()
    result = run_loop_fault(PROBES[probe_name], live.writer, now_millis=lambda: 7)
    assert result.outcome == "handled", f"{probe_name}: {result.violation_count} violation(s) {result.detail}"
    assert result.violation_count == 0
    assert _count(live.conn, "loop_fault_run") == 1
    assert _count(live.conn, "fault_handling_regression") == 0


def test_regression_detected_when_a_fault_orphans_the_task(monkeypatch):
    """If dispatch stops turning a post-start crash into a terminal (the abort path regresses), the
    fault orphans the task → the monitor fires Inv 10 → run_loop_fault reports a regression. The
    injected fault is POST-task_started (checkpoint) — a pre-start fault emits no task_started, so
    there would be no orphan to detect."""
    # neuter the abort path so a caught crash leaves the started task without a terminal
    monkeypatch.setattr("devharness.console.developer.abort", lambda *a, **k: None)
    live = _live()
    result = run_loop_fault(PROBES["git_checkpoint_128"], live.writer, now_millis=lambda: 7)
    assert result.outcome == "regression"
    assert 10 in result.invariant_numbers
    assert _count(live.conn, "loop_fault_run") == 1
    assert _count(live.conn, "fault_handling_regression") == 1


def test_run_all_loop_faults_summary():
    live = _live()
    summary = run_all_loop_faults(live.writer, now_millis=lambda: 7)
    assert summary["n_probed"] == len(PROBES)
    assert summary["n_regressions"] == 0
    assert summary["n_handled"] == len(PROBES)
    assert _count(live.conn, "loop_fault_run") == len(PROBES)


class _HeldFermata:
    def is_held(self, conn):
        return True


class _FreeFermata:
    def is_held(self, conn):
        return False


def test_scheduler_is_fermata_gated():
    live = _live()
    scheduler = LoopFaultScheduler()
    assert scheduler.step(live.conn, live.writer, _HeldFermata(), now_millis=lambda: 7) is False
    assert _count(live.conn, "loop_fault_run") == 0


def test_scheduler_runs_all_probes_per_window():
    """rev 0.3.89: one step runs the WHOLE probe set (drive() is one process/window, so a per-call
    cursor would only ever run the first probe — the gap the rev-0.3.88 live validation surfaced)."""
    live = _live()
    scheduler = LoopFaultScheduler()
    assert scheduler.step(live.conn, live.writer, _FreeFermata(), now_millis=lambda: 7) is True
    assert _count(live.conn, "loop_fault_run") == len(PROBES)
    assert _count(live.conn, "fault_handling_regression") == 0
