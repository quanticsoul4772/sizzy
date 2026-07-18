"""B2.0: Invariant 1 — single-writer lock; concurrent write fails closed."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.lock.base import LockHeldByAnotherRole, SingleWriterLock
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def test_inv1_one_holder_at_a_time():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    lock = SingleWriterLock()

    token = lock.acquire("developer", "c1", bus, conn)
    # a second writer cannot acquire while held
    with pytest.raises(LockHeldByAnotherRole):
        lock.acquire("reviewer", "c2", bus, conn)
    # exactly one holder, and it is the first acquirer
    assert conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 1
    assert conn.execute("SELECT holder_role FROM proj_lock").fetchone()[0] == "developer"

    # after release the lock is acquirable by the other role
    lock.release(token, bus, conn)
    lock.acquire("reviewer", "c2", bus, conn)
    assert conn.execute("SELECT holder_role FROM proj_lock").fetchone()[0] == "reviewer"
    assert conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 1
