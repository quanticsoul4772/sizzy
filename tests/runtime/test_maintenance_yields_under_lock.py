"""B3.6: the scheduler step yields (runs no cycle) while the write lock is held."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.maintenance.scheduler import MaintenanceScheduler
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_step_yields_under_lock_and_resumes_after_release():
    conn, bus = _setup()
    scheduler = MaintenanceScheduler()
    idle = 1_000_000  # well past the audit threshold

    bus.emit_sync("write_lock_acquired", {"lock_token": "lk", "holder_role": "developer", "correlation_id": "c", "acquired_at_millis": 1}, correlation_id="c")
    assert scheduler.step(conn, bus, idle_millis=idle, now_millis=lambda: 5) is None  # held
    assert conn.execute("SELECT count(*) FROM proj_maintenance").fetchone()[0] == 0  # nothing ran

    bus.emit_sync("write_lock_released", {"lock_token": "lk", "holder_role": "developer", "correlation_id": "c", "released_at_millis": 2}, correlation_id="c")
    ran = scheduler.step(conn, bus, idle_millis=idle, now_millis=lambda: 5)
    assert ran == "audit"  # deepest unlocked at this idle duration
    assert conn.execute("SELECT count(*) FROM proj_maintenance WHERE cycle_kind='audit'").fetchone()[0] >= 1


def test_step_yields_too_soon():
    conn, bus = _setup()
    scheduler = MaintenanceScheduler()
    assert scheduler.step(conn, bus, idle_millis=10_000, now_millis=lambda: 5) is None  # below the gentlest threshold
    assert conn.execute("SELECT count(*) FROM proj_maintenance").fetchone()[0] == 0
