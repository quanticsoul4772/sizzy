"""B2.8: trust handlers update proj_trust_grants; rebuild parity across grant->renew->revoke."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, registry, EventBus(conn, registry)


def _grant_renew_revoke(bus):
    bus.emit_sync("trust_granted", {"role_name": "developer", "task_class": "c", "brier_at_grant": 0.1, "granted_at_millis": 100, "expires_at_millis": 200, "granted_by": "op", "correlation_id": "x"}, correlation_id="x")
    bus.emit_sync("trust_renewed", {"role_name": "developer", "task_class": "c", "brier_at_renewal": 0.08, "renewed_at_millis": 150, "new_expires_at_millis": 400, "renewed_by": "op", "correlation_id": "x"}, correlation_id="x")
    bus.emit_sync("trust_revoked", {"role_name": "developer", "task_class": "c", "reason": "regressed", "revoked_at_millis": 300, "revoked_by": "op", "correlation_id": "x"}, correlation_id="x")


def test_handlers_track_grant_renew_revoke():
    conn, _registry, bus = _setup()
    _grant_renew_revoke(bus)
    row = conn.execute("SELECT brier_at_grant, expires_at_millis, revoked_at_millis FROM proj_trust_grants").fetchone()
    assert row == (0.1, 400, 300)  # renewed expiry, then revoked


def test_rebuild_parity():
    conn, registry, bus = _setup()
    _grant_renew_revoke(bus)
    assert check_projection_rebuild_parity(conn, registry) is True
