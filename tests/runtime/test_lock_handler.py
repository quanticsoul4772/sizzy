"""B2.0: lock projection handlers + rebuild parity."""

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


def test_acquire_inserts_release_deletes():
    conn, _registry, bus = _setup()
    bus.emit_sync(
        "write_lock_acquired",
        {"lock_token": "t1", "holder_role": "developer", "correlation_id": "c", "acquired_at_millis": 1},
        correlation_id="c",
    )
    assert conn.execute("SELECT holder_role FROM proj_lock WHERE lock_token='t1'").fetchone()[0] == "developer"
    bus.emit_sync(
        "write_lock_released",
        {"lock_token": "t1", "holder_role": "developer", "correlation_id": "c", "released_at_millis": 2},
        correlation_id="c",
    )
    assert conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 0


def test_rebuild_parity_across_acquire_release():
    conn, registry, bus = _setup()
    bus.emit_sync("write_lock_acquired", {"lock_token": "t1", "holder_role": "developer", "correlation_id": "c", "acquired_at_millis": 1}, correlation_id="c")
    bus.emit_sync("write_lock_released", {"lock_token": "t1", "holder_role": "developer", "correlation_id": "c", "released_at_millis": 2}, correlation_id="c")
    assert check_projection_rebuild_parity(conn, registry) is True


def test_rebuild_parity_held_state():
    # acquire with no release: the held row must reproduce on rebuild
    conn, registry, bus = _setup()
    bus.emit_sync("write_lock_acquired", {"lock_token": "t9", "holder_role": "developer", "correlation_id": "c", "acquired_at_millis": 7}, correlation_id="c")
    assert check_projection_rebuild_parity(conn, registry) is True
    assert conn.execute("SELECT holder_role FROM proj_lock WHERE lock_token='t9'").fetchone()[0] == "developer"
