"""B3.6: fermata holds under active work; graduated pressure unlocks deeper cycles by idle time."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.maintenance.fermata import FermataPacing
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_held_while_lock_acquired_released_on_release():
    conn, bus = _setup()
    fermata = FermataPacing()
    assert fermata.is_held(conn) is False  # idle
    bus.emit_sync("write_lock_acquired", {"lock_token": "lk", "holder_role": "developer", "correlation_id": "c", "acquired_at_millis": 1}, correlation_id="c")
    assert fermata.is_held(conn) is True  # writer holds the lock
    bus.emit_sync("write_lock_released", {"lock_token": "lk", "holder_role": "developer", "correlation_id": "c", "released_at_millis": 2}, correlation_id="c")
    assert fermata.is_held(conn) is False


def test_held_while_task_running():
    conn, bus = _setup()
    fermata = FermataPacing()
    bus.emit_sync("task_started", {"task_id": "t1", "role": "developer", "worktree_path": "/w", "correlation_id": "c", "started_at_millis": 1}, correlation_id="c")
    assert fermata.is_held(conn) is True  # a started task without a terminal
    bus.emit_sync("terminal_outcome", {"task_id": "t1", "outcome": "completed", "detail": "", "reason": "", "correlation_id": "c", "terminated_at_millis": 2}, correlation_id="c")
    assert fermata.is_held(conn) is False


def test_graduated_pressure_unlocks_by_idle():
    fermata = FermataPacing()
    assert fermata.unlocked_cycles(30_000) == []  # too soon
    assert fermata.unlocked_cycles(60_000) == ["consolidate"]
    assert fermata.unlocked_cycles(300_000) == ["consolidate", "prune"]
    assert fermata.unlocked_cycles(900_000) == ["consolidate", "prune", "audit"]
    assert fermata.unlocked_cycles(3_600_000) == ["consolidate", "prune", "audit", "synthesize"]
    assert fermata.deepest_cycle(120_000) == "consolidate"
    assert fermata.deepest_cycle(1_000_000) == "audit"
