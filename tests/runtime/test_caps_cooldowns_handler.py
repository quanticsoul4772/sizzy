"""B4.6: budget_exceeded handler projects OSS kinds only; rebuild parity holds."""

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


def test_oss_kinds_projected_b2x_skipped():
    conn, _registry, bus = _setup()
    bus.emit_sync("budget_exceeded", {"budget_kind": "oss_wall_clock", "limit_value": 100.0, "observed_value": 150.0, "action_taken": "abort", "subject_id": "t1", "exceeded_at_millis": 5}, correlation_id="c1")
    # a B2.x per-role overrun must NOT be projected (and must not violate the CHECK)
    bus.emit_sync("budget_exceeded", {"role": "director", "budget_kind": "reasoning", "limit": 1.0, "spent": 2.0}, correlation_id="c2")
    rows = conn.execute("SELECT budget_kind, subject_id, action_taken FROM proj_budget_exceeded").fetchall()
    assert rows == [("oss_wall_clock", "t1", "abort")]


def test_rebuild_parity_mixed():
    conn, registry, bus = _setup()
    bus.emit_sync("budget_exceeded", {"budget_kind": "oss_usd", "limit_value": 5.0, "observed_value": 6.0, "action_taken": "abort", "subject_id": "t1", "exceeded_at_millis": 5}, correlation_id="c1")
    bus.emit_sync("budget_exceeded", {"budget_kind": "oss_requester_cooldown", "action_taken": "refuse", "subject_id": "r1", "exceeded_at_millis": 6}, correlation_id="c2")
    bus.emit_sync("budget_exceeded", {"role": "director", "budget_kind": "token", "limit": 1.0, "spent": 2.0}, correlation_id="c3")
    assert check_projection_rebuild_parity(conn, registry) is True
