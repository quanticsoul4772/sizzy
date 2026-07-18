"""B0.3 parity test (Invariant 8 / check_projection_rebuild_parity).

With zero registered projections the check is vacuously green; this is expected
and correct until projections land (operator design pending). The test confirms
the check returns True over a populated event log with an empty registry, and
that rebuild() is a no-op that does not error and does not touch the event log.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import migrate
from devharness.events.bus import EventBus
from devharness.projections.registry import ProjectionRegistry
from devharness.projections.parity import check_projection_rebuild_parity, rebuild


def _db_with_events() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    for i in range(3):
        bus.emit_sync("task.created", {"n": i}, correlation_id="corr-1")
    return conn


def test_parity_vacuously_green_with_empty_registry():
    conn = _db_with_events()
    assert check_projection_rebuild_parity(conn, ProjectionRegistry()) is True


def test_rebuild_is_noop_with_empty_registry():
    conn = _db_with_events()
    rebuild(conn, ProjectionRegistry())
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 3
