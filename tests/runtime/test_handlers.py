"""B0.4 handler/projection test.

A sample event emits and one projection updates via its handler: a
role_transitioned event drives proj_role_state through rebuild() (replay).
Parity stays green over the 12 registered projection tables.
"""

import sqlite3
import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import migrate
from devharness.events.bus import EventBus
from devharness.events.registry import RoleTransitioned
from devharness.projections.registry import ProjectionRegistry
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import rebuild, check_projection_rebuild_parity


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    migrate(conn)  # applies 0001 + 0002
    return conn


def test_role_transitioned_updates_proj_role_state():
    conn = _db()
    bus = EventBus(conn)
    payload = msgspec.to_builtins(RoleTransitioned(from_role="research", to_role="director"))
    bus.emit_sync("role_transitioned", payload, correlation_id="corr-1")

    registry = ProjectionRegistry()
    register_handlers(registry)
    rebuild(conn, registry)

    row = conn.execute("SELECT role, event_seq FROM proj_role_state WHERE id = 1").fetchone()
    assert row == ("director", 1)


def test_parity_green_over_registered_projections():
    conn = _db()
    bus = EventBus(conn)
    for to_role in ("director", "developer", "reviewer"):
        payload = msgspec.to_builtins(RoleTransitioned(from_role="research", to_role=to_role))
        bus.emit_sync("role_transitioned", payload, correlation_id="corr-1")

    registry = ProjectionRegistry()
    register_handlers(registry)
    rebuild(conn, registry)
    assert check_projection_rebuild_parity(conn, registry) is True
    # last write wins on the singleton row
    assert conn.execute("SELECT role FROM proj_role_state WHERE id = 1").fetchone()[0] == "reviewer"
