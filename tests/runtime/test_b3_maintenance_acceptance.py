"""B3.9 acceptance: maintenance ticks under a fermata trigger after the write loop."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.maintenance.fermata import FermataPacing
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


def _completed_loop(bus):
    # a finished write loop: task started + terminal, lock acquired + released (idle afterwards)
    bus.emit_sync("task_started", {"task_id": "t1", "role": "developer", "worktree_path": "/w", "correlation_id": "c", "started_at_millis": 1}, correlation_id="c")
    bus.emit_sync("write_lock_acquired", {"lock_token": "lk", "holder_role": "developer", "correlation_id": "c", "acquired_at_millis": 1}, correlation_id="c")
    bus.emit_sync("write_lock_released", {"lock_token": "lk", "holder_role": "developer", "correlation_id": "c", "released_at_millis": 2}, correlation_id="c")
    bus.emit_sync("terminal_outcome", {"task_id": "t1", "outcome": "completed", "detail": "", "reason": "", "correlation_id": "c", "terminated_at_millis": 3}, correlation_id="c")


def test_consolidate_then_prune_by_graduated_pressure():
    conn, bus = _setup()
    _completed_loop(bus)
    scheduler = MaintenanceScheduler()

    # idle past the consolidate threshold (60s) -> consolidate runs
    assert scheduler.step(conn, bus, idle_millis=60_000, now_millis=lambda: 100) == "consolidate"
    # idle past the prune threshold (300s) -> the deepest unlocked is prune (advisory, no deletion)
    assert scheduler.step(conn, bus, idle_millis=300_000, now_millis=lambda: 200) == "prune"

    kinds = {r[0] for r in conn.execute("SELECT cycle_kind FROM proj_maintenance")}
    assert {"consolidate", "prune"} <= kinds
    # prune is advisory: no deletion happened, only a maintenance_action describing it
    prune_action = conn.execute("SELECT action_description FROM proj_maintenance WHERE cycle_kind='prune' AND event_kind='action'").fetchone()[0]
    assert "prune" in prune_action and "no deletion" in prune_action


def test_fermata_pauses_under_lock_resumes_on_release():
    conn, bus = _setup()
    _completed_loop(bus)
    scheduler = MaintenanceScheduler()
    fermata = FermataPacing()

    # a fresh writer acquires the lock mid-window -> maintenance pauses
    bus.emit_sync("write_lock_acquired", {"lock_token": "lk2", "holder_role": "developer", "correlation_id": "c2", "acquired_at_millis": 10}, correlation_id="c2")
    assert fermata.is_held(conn) is True
    assert scheduler.step(conn, bus, idle_millis=60_000, now_millis=lambda: 100) is None  # held, nothing ran
    assert conn.execute("SELECT count(*) FROM proj_maintenance").fetchone()[0] == 0

    # lock released -> resumes
    bus.emit_sync("write_lock_released", {"lock_token": "lk2", "holder_role": "developer", "correlation_id": "c2", "released_at_millis": 11}, correlation_id="c2")
    assert scheduler.step(conn, bus, idle_millis=60_000, now_millis=lambda: 200) == "consolidate"
    assert conn.execute("SELECT count(*) FROM proj_maintenance").fetchone()[0] >= 1
