"""emit_sync is atomic under concurrency (rev 0.3.97): BEGIN IMMEDIATE holds the sqlite write lock across
the tail-hash read + append, so two writers on one store can't fork the chain (Inv 7); and a mandatory
rollback on any error never leaves a dangling transaction on the shared connection.
"""

import sqlite3
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus, verify_chain
from devharness.migrate import migrate


def test_concurrent_writers_do_not_fork_the_chain(tmp_path):
    """The tripwire: N threads, each its OWN connection + busy_timeout, start together on a barrier and
    each emit M events to one file store. With BEGIN IMMEDIATE they serialize on the write lock and the
    chain stays intact; without it, two threads read the same tail and fork (verify_chain would raise)."""
    db = tmp_path / "concurrent.db"
    setup = sqlite3.connect(str(db))
    migrate(setup)
    setup.close()

    N, M = 4, 25
    barrier = threading.Barrier(N)
    errors = []

    def worker(wid):
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA busy_timeout=10000")  # block on the write lock instead of 'database is locked'
        bus = EventBus(conn)
        try:
            barrier.wait()  # all threads hit the contended append window at once
            for i in range(M):
                bus.emit_sync("gate_fired", {"w": wid, "i": i}, correlation_id="c")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    check = sqlite3.connect(str(db))
    assert verify_chain(check) == N * M  # no fork, and every event landed
    check.close()


class _RaisingRegistry:
    """A registry whose sole handler raises — to exercise the mid-emit rollback."""

    def handlers_for(self, event_type):
        def _boom(conn, event):
            raise RuntimeError("handler boom")
        return [_boom]


def test_handler_error_rolls_back_and_frees_the_transaction(tmp_path):
    """The load-bearing case: a projection handler raising mid-emit must roll the event back AND leave no
    dangling transaction on the shared connection, so the NEXT emit_sync on it still works."""
    db = tmp_path / "rollback.db"
    conn = sqlite3.connect(str(db))
    migrate(conn)

    with pytest.raises(RuntimeError):
        EventBus(conn, registry=_RaisingRegistry()).emit_sync("gate_fired", {}, correlation_id="c")

    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0  # rolled back, not persisted
    assert conn.in_transaction is False                                     # no dangling transaction
    EventBus(conn).emit_sync("gate_fired", {"ok": 1}, correlation_id="c")   # next emit on the same conn works
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_serial_emits_still_chain(tmp_path):
    db = tmp_path / "serial.db"
    conn = sqlite3.connect(str(db))
    migrate(conn)
    bus = EventBus(conn)
    for i in range(5):
        bus.emit_sync("gate_fired", {"i": i}, correlation_id="c")
    assert verify_chain(conn) == 5
