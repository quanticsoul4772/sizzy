"""B3.7: the adversarial scheduler does not run a probe while the write lock is held."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.adversarial.scheduler import AdversarialScheduler
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


def test_yields_under_lock_resumes_after_release():
    conn, bus = _setup()
    scheduler = AdversarialScheduler()
    fermata = FermataPacing()

    bus.emit_sync("write_lock_acquired", {"lock_token": "lk", "holder_role": "developer", "correlation_id": "c", "acquired_at_millis": 1}, correlation_id="c")
    assert scheduler.step(conn, bus, fermata, now_millis=lambda: 5) is False
    assert conn.execute("SELECT count(*) FROM proj_adversarial").fetchone()[0] == 0  # nothing probed

    bus.emit_sync("write_lock_released", {"lock_token": "lk", "holder_role": "developer", "correlation_id": "c", "released_at_millis": 2}, correlation_id="c")
    assert scheduler.step(conn, bus, fermata, now_millis=lambda: 5) is True
    from devharness.adversarial.probes import PROBES
    assert conn.execute("SELECT count(*) FROM proj_adversarial").fetchone()[0] == len(PROBES)  # whole set (rev 0.3.90)
