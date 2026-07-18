"""B2.8: calibrated-trust promotion lifecycle."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.calibration.promotion import grant, has_active_trust, renew, revoke
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_grant_creates_active_trust():
    conn, bus = _setup()
    grant("developer", "new_project_scaffold", 0.1, "operator", conn, bus, now_millis=lambda: 1000, expiry_days=7)
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='trust_granted'").fetchone()[0] == 1
    assert has_active_trust("developer", "new_project_scaffold", conn, now_millis=lambda: 2000) is True


def test_renew_extends_expiry():
    conn, bus = _setup()
    grant("developer", "new_project_scaffold", 0.1, "operator", conn, bus, now_millis=lambda: 1000, expiry_days=1)
    before = conn.execute("SELECT expires_at_millis FROM proj_trust_grants").fetchone()[0]
    renew("developer", "new_project_scaffold", 0.08, "operator", conn, bus, now_millis=lambda: 2000, expiry_days=7)
    after = conn.execute("SELECT expires_at_millis FROM proj_trust_grants").fetchone()[0]
    assert after > before


def test_revoke_ends_trust():
    conn, bus = _setup()
    grant("developer", "new_project_scaffold", 0.1, "operator", conn, bus, now_millis=lambda: 1000, expiry_days=7)
    revoke("developer", "new_project_scaffold", "calibration regressed", "operator", conn, bus, now_millis=lambda: 1500)
    assert conn.execute("SELECT revoked_at_millis FROM proj_trust_grants").fetchone()[0] == 1500
    assert has_active_trust("developer", "new_project_scaffold", conn, now_millis=lambda: 2000) is False


def test_expired_trust_is_inactive():
    conn, bus = _setup()
    grant("developer", "new_project_scaffold", 0.1, "operator", conn, bus, now_millis=lambda: 1000, expiry_days=1)
    far_future = 1000 + 2 * 24 * 60 * 60 * 1000
    assert has_active_trust("developer", "new_project_scaffold", conn, now_millis=lambda: far_future) is False


def test_no_grant_no_trust():
    conn, _bus = _setup()
    assert has_active_trust("developer", "new_project_scaffold", conn) is False
