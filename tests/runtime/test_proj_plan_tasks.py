"""B3.0: proj_plan_tasks per-task state + CHECK + rebuild parity."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, registry, EventBus(conn, registry)


def _dispatch(bus, plan_id, task_id, task_class="feature", deps="[]"):
    bus.emit_sync("task_dispatched", {"plan_id": plan_id, "task_id": task_id, "dispatched_to_role": "developer", "dispatched_by_role": "director", "correlation_id": "c", "dispatched_at_millis": 1, "task_class": task_class, "dependency_task_ids": deps}, correlation_id="c")


def _terminal(bus, task_id, outcome="completed"):
    bus.emit_sync("terminal_outcome", {"task_id": task_id, "outcome": outcome, "detail": "", "reason": "", "correlation_id": "c", "terminated_at_millis": 5}, correlation_id="c")


def test_insert_update_sequence():
    conn, _registry, bus = _setup()
    bus.emit_sync("plan_drafted", {"plan_id": "p1", "spec_id": "s", "task_count": 2}, correlation_id="c")
    _dispatch(bus, "p1", "t1", task_class="feature", deps="[]")
    # running on dispatch, current_task_id points to it
    assert conn.execute("SELECT task_state, task_class FROM proj_plan_tasks WHERE task_id='t1'").fetchone() == ("running", "feature")
    assert conn.execute("SELECT current_task_id FROM proj_plan WHERE plan_id='p1'").fetchone()[0] == "t1"
    _terminal(bus, "t1", "completed")
    # completed; plan still executing (1 of 2); current_task_id cleared
    assert conn.execute("SELECT task_state, completed_at_millis FROM proj_plan_tasks WHERE task_id='t1'").fetchone() == ("completed", 5)
    assert conn.execute("SELECT current_state, current_task_id FROM proj_plan WHERE plan_id='p1'").fetchone() == ("executing", None)
    _dispatch(bus, "p1", "t2", deps='["t1"]')
    _terminal(bus, "t2", "completed")
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id='p1'").fetchone()[0] == "completed"


def test_check_constraint_rejects_bad_state():
    conn, _registry, _bus = _setup()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_plan_tasks (plan_id, task_id, task_state) VALUES ('p', 't', 'nope')")


def test_rebuild_parity():
    conn, registry, bus = _setup()
    bus.emit_sync("plan_drafted", {"plan_id": "p1", "spec_id": "s", "task_count": 2}, correlation_id="c")
    _dispatch(bus, "p1", "t1")
    _terminal(bus, "t1", "completed")
    _dispatch(bus, "p1", "t2", deps='["t1"]')
    _terminal(bus, "t2", "rejected")
    assert check_projection_rebuild_parity(conn, registry) is True
    # any-rejected -> blocked
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id='p1'").fetchone()[0] == "blocked"
