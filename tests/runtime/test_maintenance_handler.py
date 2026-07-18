"""B3.6: maintenance handlers update proj_maintenance; rebuild parity across tick+action."""

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


def _emit(bus):
    bus.emit_sync("maintenance_tick", {"cycle_kind": "consolidate", "tick_at_millis": 10, "correlation_id": "m"}, correlation_id="m")
    bus.emit_sync("maintenance_action", {"cycle_kind": "consolidate", "action_description": "digest of 3 plans", "evidence": {"plan_count": 3}, "correlation_id": "m", "action_at_millis": 11}, correlation_id="m")
    bus.emit_sync("maintenance_tick", {"cycle_kind": "audit", "tick_at_millis": 20, "correlation_id": "m"}, correlation_id="m")
    bus.emit_sync("maintenance_action", {"cycle_kind": "audit", "action_description": "chain valid", "evidence": {"chain_valid": True}, "correlation_id": "m", "action_at_millis": 21}, correlation_id="m")


def test_handlers_record_tick_and_action():
    conn, _registry, bus = _setup()
    _emit(bus)
    rows = conn.execute("SELECT cycle_kind, event_kind, action_description FROM proj_maintenance ORDER BY maintenance_row_id").fetchall()
    assert rows == [
        ("consolidate", "tick", None),
        ("consolidate", "action", "digest of 3 plans"),
        ("audit", "tick", None),
        ("audit", "action", "chain valid"),
    ]


def test_rebuild_parity():
    conn, registry, bus = _setup()
    _emit(bus)
    assert check_projection_rebuild_parity(conn, registry) is True
