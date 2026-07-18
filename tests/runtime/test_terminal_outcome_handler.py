"""B2.6: terminal_outcome drives proj_task_lifecycle; parity holds."""

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


def _start(bus, task_id="t1"):
    bus.emit_sync(
        "task_started",
        {"task_id": task_id, "role": "developer", "worktree_path": "/w", "correlation_id": "c", "started_at_millis": 1},
        correlation_id="c",
    )


def _terminate(bus, task_id, outcome, reason="", at=9):
    bus.emit_sync(
        "terminal_outcome",
        {"task_id": task_id, "outcome": outcome, "detail": reason, "reason": reason, "correlation_id": "c", "terminated_at_millis": at},
        correlation_id="c",
    )


def test_task_started_sets_running():
    conn, _registry, bus = _setup()
    _start(bus)
    row = conn.execute("SELECT current_state, started_at_millis, terminal_at_millis FROM proj_task_lifecycle WHERE task_id='t1'").fetchone()
    assert row == ("running", 1, None)


@pytest.mark.parametrize("outcome,state", [("completed", "completed"), ("rejected", "rejected"), ("aborted", "aborted")])
def test_terminal_outcome_updates_state(outcome, state):
    conn, _registry, bus = _setup()
    _start(bus)
    _terminate(bus, "t1", outcome, reason="r")
    row = conn.execute("SELECT current_state, terminal_at_millis, outcome, reason FROM proj_task_lifecycle WHERE task_id='t1'").fetchone()
    assert row == (state, 9, outcome, "r")


def test_rebuild_parity_start_to_terminal():
    conn, registry, bus = _setup()
    _start(bus, "t1")
    _terminate(bus, "t1", "completed")
    _start(bus, "t2")
    _terminate(bus, "t2", "aborted", reason="budget")
    assert check_projection_rebuild_parity(conn, registry) is True
