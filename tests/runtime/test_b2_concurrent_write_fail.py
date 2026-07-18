"""B2.10: concurrent-write fail — a second writer cannot acquire the held lock (Inv 1)."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.gates.base import GateDeny, GateOk
from devharness.gates.write_lock import WriteLockGate
from devharness.lock.base import LockHeldByAnotherRole, SingleWriterLock
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_second_acquire_fails_and_gate_denies():
    conn, bus = _setup()
    lock = SingleWriterLock()
    token = lock.acquire("developer", "c1", bus, conn)  # first writer holds

    # a second writer (different role/correlation) is refused
    with pytest.raises(LockHeldByAnotherRole):
        lock.acquire("reviewer", "c2", bus, conn)

    # the write-lock gate denies the second role with the documented envelope
    deny = WriteLockGate().check({"conn": conn, "holder_role": "reviewer"})
    assert isinstance(deny, GateDeny)
    assert deny.reason == "Write lock held by developer for correlation_id c1"
    assert "Single-writer invariant" in deny.purpose

    # the original holder still owns the lock; no second row registered
    assert conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 1
    assert conn.execute("SELECT holder_role, correlation_id FROM proj_lock").fetchone() == ("developer", "c1")
    # the same holder passes the gate
    assert isinstance(WriteLockGate().check({"conn": conn, "holder_role": "developer"}), GateOk)

    # release returns the lock to acquirable
    lock.release(token, bus, conn)
    lock.acquire("reviewer", "c2", bus, conn)
    assert conn.execute("SELECT holder_role FROM proj_lock").fetchone()[0] == "reviewer"
