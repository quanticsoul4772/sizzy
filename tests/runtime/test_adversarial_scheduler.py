"""B3.7: adversarial scheduler yields under fermata hold; runs the whole probe set otherwise (rev 0.3.90)."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.adversarial.probes import PROBES
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


def test_yields_when_fermata_held():
    conn, bus = _setup()
    bus.emit_sync("write_lock_acquired", {"lock_token": "lk", "holder_role": "developer", "correlation_id": "c", "acquired_at_millis": 1}, correlation_id="c")
    scheduler = AdversarialScheduler()
    assert scheduler.step(conn, bus, FermataPacing(), now_millis=lambda: 5) is False
    assert conn.execute("SELECT count(*) FROM proj_adversarial").fetchone()[0] == 0


def test_runs_whole_probe_set_per_window():
    conn, bus = _setup()
    scheduler = AdversarialScheduler()
    fermata = FermataPacing()
    # rev 0.3.90: one step runs every probe once (drive() is one process/window, so a per-call cursor
    # would only ever run the first probe in production).
    assert scheduler.step(conn, bus, fermata, now_millis=lambda: 5) is True
    probed = {r[0] for r in conn.execute("SELECT probe_name FROM proj_adversarial")}
    assert probed == set(PROBES.keys())
