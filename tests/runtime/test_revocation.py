"""B4.6: revocation — an effectively-permanent cooldown + budget_exceeded(requester_revoked)."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.oss.cooldowns import check_cooldown
from devharness.oss.revocation import revoke_requester
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_revoke_inserts_permanent_cooldown_and_emits():
    conn, bus = _setup()
    revoke_requester("r1", "repeated abuse", "operator", conn, bus, "c", now_millis_fn=lambda: 1000)
    row = conn.execute("SELECT triggered_by, cooldown_until_millis FROM proj_requester_cooldown WHERE requester_id='r1'").fetchone()
    assert row[0] == "revocation" and row[1] > 1000 + 50 * 365 * 24 * 60 * 60 * 1000  # ~permanent
    ev = conn.execute("SELECT json_extract(payload, '$.budget_kind'), json_extract(payload, '$.reason') FROM events WHERE event_type='budget_exceeded'").fetchone()
    assert ev == ("requester_revoked", "repeated abuse")
    assert conn.execute("SELECT count(*) FROM proj_budget_exceeded WHERE budget_kind='requester_revoked'").fetchone()[0] == 1


def test_revoked_requester_in_cooldown_indefinitely():
    conn, bus = _setup()
    revoke_requester("r1", "spam", "operator", conn, bus, "c", now_millis_fn=lambda: 1000)
    far_future = 1000 + 10 * 365 * 24 * 60 * 60 * 1000  # 10 years later
    assert check_cooldown("r1", conn, lambda: far_future).active is True
