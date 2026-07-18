"""B5.0: RetroScheduler — picks the next unprocessed terminal, fires retro_run, honors fermata."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.scheduler import RetroScheduler


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _terminal(bus, task_id, outcome, correlation_id="c"):
    bus.emit_sync("terminal_outcome", {"task_id": task_id, "outcome": outcome, "detail": "",
                  "correlation_id": correlation_id, "terminated_at_millis": 1}, correlation_id=correlation_id)


def test_step_processes_next_terminal_and_fires_retro_run():
    conn, bus = _setup()
    _terminal(bus, "t1", "completed")
    sched = RetroScheduler()
    assert sched.step(conn, bus, now_millis=lambda: 5) == "t1"
    row = conn.execute("SELECT source_task_id, terminal_kind, llm_invoked, candidates_emitted_count FROM proj_retro_runs").fetchone()
    assert row == ("t1", "completed", 0, 0)  # B5.0 stub: no candidates, no LLM
    # the retro_run is in the task's correlation chain
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='retro_run' AND correlation_id='c'").fetchone()[0] == 1


def test_marks_processed_and_advances():
    conn, bus = _setup()
    _terminal(bus, "t1", "completed")
    _terminal(bus, "t2", "rejected")
    sched = RetroScheduler()
    assert sched.step(conn, bus, now_millis=lambda: 5) == "t1"
    assert sched.step(conn, bus, now_millis=lambda: 6) == "t2"  # advances to the next unprocessed
    assert sched.step(conn, bus, now_millis=lambda: 7) is None  # queue drained, idempotent
    assert conn.execute("SELECT count(*) FROM proj_retro_runs").fetchone()[0] == 2


def test_yields_under_fermata():
    conn, bus = _setup()
    _terminal(bus, "t1", "completed")
    # simulate active work (a held write lock) -> the fermata holds -> step yields
    conn.execute("INSERT INTO proj_lock (lock_token, holder_role, correlation_id, acquired_at_millis) VALUES ('lk', 'developer', 'c', 1)")
    conn.commit()
    sched = RetroScheduler()
    assert sched.step(conn, bus, now_millis=lambda: 5) is None
    assert conn.execute("SELECT count(*) FROM proj_retro_runs").fetchone()[0] == 0  # nothing processed while held


def test_sibling_tasks_share_correlation_but_dedup_by_task():
    # terminals for two tasks in the same plan share correlation_id; each must get its own retro_run
    conn, bus = _setup()
    _terminal(bus, "plan-t0", "completed", correlation_id="plan-c")
    _terminal(bus, "plan-t1", "completed", correlation_id="plan-c")
    sched = RetroScheduler()
    assert sched.step(conn, bus, now_millis=lambda: 5) == "plan-t0"
    assert sched.step(conn, bus, now_millis=lambda: 6) == "plan-t1"  # not skipped despite shared correlation_id
    assert {r[0] for r in conn.execute("SELECT source_task_id FROM proj_retro_runs")} == {"plan-t0", "plan-t1"}


def test_re_driven_task_second_terminal_is_analyzed():
    # #6: a task that rejects then (after a re-drive) completes emits TWO terminal_outcomes for the same
    # task_id. Dedup by (task_id, kind) — not task_id alone — so the COMPLETION is still analyzed, not lost
    # to the learning spine (which previously saw only the rejection forever).
    conn, bus = _setup()
    _terminal(bus, "t1", "rejected")     # attempt 1
    _terminal(bus, "t1", "completed")    # attempt 2 (re-drive)
    sched = RetroScheduler()
    assert sched.step(conn, bus, now_millis=lambda: 5) == "t1"   # the rejection
    assert sched.step(conn, bus, now_millis=lambda: 6) == "t1"   # the completion (different kind) — analyzed
    assert sched.step(conn, bus, now_millis=lambda: 7) is None
    kinds = {r[0] for r in conn.execute("SELECT terminal_kind FROM proj_retro_runs WHERE source_task_id='t1'")}
    assert kinds == {"rejected", "completed"}   # both attempts' outcomes reached the spine


def test_same_kind_re_terminal_is_deduped():
    # the accepted residual: two SAME-kind terminals for one task -> only the first is analyzed
    conn, bus = _setup()
    _terminal(bus, "t1", "rejected")
    _terminal(bus, "t1", "rejected")
    sched = RetroScheduler()
    assert sched.step(conn, bus, now_millis=lambda: 5) == "t1"
    assert sched.step(conn, bus, now_millis=lambda: 6) is None   # the second same-kind terminal is deduped
    assert conn.execute("SELECT count(*) FROM proj_retro_runs WHERE source_task_id='t1'").fetchone()[0] == 1
