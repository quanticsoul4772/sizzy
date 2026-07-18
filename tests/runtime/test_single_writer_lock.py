"""B2.0: SingleWriterLock acquire/release semantics."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.lock.base import LockHeldByAnotherRole, LockNotHeld, LockToken, SingleWriterLock
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    return conn, bus, SingleWriterLock()


def test_acquire_then_release():
    conn, bus, lock = _setup()
    token = lock.acquire("developer", "c1", bus, conn, now_millis=lambda: 1)
    assert conn.execute("SELECT holder_role FROM proj_lock").fetchone()[0] == "developer"
    lock.release(token, bus, conn, now_millis=lambda: 2)
    assert conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 0


def test_second_acquire_while_held_raises():
    conn, bus, lock = _setup()
    lock.acquire("developer", "c1", bus, conn)
    with pytest.raises(LockHeldByAnotherRole):
        lock.acquire("reviewer", "c2", bus, conn)


def test_release_returns_lock_to_acquirable():
    conn, bus, lock = _setup()
    token = lock.acquire("developer", "c1", bus, conn)
    lock.release(token, bus, conn)
    lock.acquire("reviewer", "c2", bus, conn)  # now free
    assert conn.execute("SELECT holder_role FROM proj_lock").fetchone()[0] == "reviewer"


def test_release_unheld_token_raises():
    conn, bus, lock = _setup()
    with pytest.raises(LockNotHeld):
        lock.release(LockToken("nope", "developer", "c1"), bus, conn)


def test_acquire_and_release_emit_lock_events():
    conn, bus, lock = _setup()
    token = lock.acquire("developer", "c1", bus, conn)
    lock.release(token, bus, conn)
    types = [r[0] for r in conn.execute("SELECT event_type FROM events ORDER BY seq")]
    assert types == ["write_lock_acquired", "write_lock_released"]
