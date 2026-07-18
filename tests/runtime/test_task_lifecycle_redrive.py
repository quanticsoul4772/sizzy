"""Audit #low1: a re-driven task's lifecycle row must clear the prior attempt's terminal fields.

handle_task_started's ON CONFLICT set current_state='running' but left terminal_at_millis/outcome/reason
from the prior rejection, so the row was self-contradictory (running + terminal set) and the AuditCycle
(terminal_at_millis IS NULL = in-flight) undercounted a re-driven running task.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _started(bus):
    bus.emit_sync("task_started", {"task_id": "t1", "role": "developer", "worktree_path": "/w",
                                   "correlation_id": "c", "started_at_millis": 1}, correlation_id="c")


def _rejected(bus):
    bus.emit_sync("terminal_outcome", {"task_id": "t1", "outcome": "rejected", "detail": "x",
                                       "reason": "x", "correlation_id": "c", "terminated_at_millis": 2},
                  correlation_id="c")


def _row(conn):
    return conn.execute(
        "SELECT current_state, terminal_at_millis, outcome, reason FROM proj_task_lifecycle WHERE task_id='t1'"
    ).fetchone()


def test_redrive_clears_prior_terminal_fields():
    conn, bus = _setup()
    _started(bus); _rejected(bus)
    state, term_at, outcome, _ = _row(conn)
    assert state == "rejected" and term_at is not None and outcome == "rejected"   # terminal after attempt 1

    _started(bus)   # re-drive: the task is running again
    assert _row(conn) == ("running", None, None, None)   # not self-contradictory; counts as in-flight
