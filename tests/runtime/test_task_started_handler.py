"""B2.3: task_started emit inserts proj_task_started; rebuild parity holds."""

import sqlite3
import sys
from pathlib import Path

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


def test_emit_inserts_proj_task_started():
    conn, _registry, bus = _setup()
    bus.emit_sync(
        "task_started",
        {"task_id": "t1", "role": "developer", "worktree_path": "/w/t1", "correlation_id": "c", "started_at_millis": 5},
        correlation_id="c",
    )
    row = conn.execute(
        "SELECT role, worktree_path, started_at_millis FROM proj_task_started WHERE task_id='t1'"
    ).fetchone()
    assert row == ("developer", "/w/t1", 5)


def test_rebuild_parity_reproduces():
    conn, registry, bus = _setup()
    bus.emit_sync(
        "task_started",
        {"task_id": "t1", "role": "developer", "worktree_path": "/w/t1", "correlation_id": "c", "started_at_millis": 5},
        correlation_id="c",
    )
    assert check_projection_rebuild_parity(conn, registry) is True
