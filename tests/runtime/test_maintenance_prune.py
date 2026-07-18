"""Operator-authorized prune (§S6): the delete path the advisory PruneCycle deliberately lacks.

The maintenance cycles never delete data; this authorized companion actually removes EXPIRED trust
grants via trust_grant_pruned events. Requires operator authorization; only touches expired grants.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import msgspec
import pytest

from devharness.events.bus import EventBus
from devharness.events.registry import TrustGranted
from devharness.maintenance.prune import prune_expired_trust_grants
from devharness.migrate import migrate
from devharness.projections.handlers import HANDLERS, register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _grant(bus, role, cls, granted_at, expires_at):
    bus.emit_sync(
        "trust_granted",
        msgspec.to_builtins(TrustGranted(
            role_name=role, task_class=cls, brier_at_grant=0.1, granted_at_millis=granted_at,
            expires_at_millis=expires_at, granted_by="calibration", correlation_id="c")),
        correlation_id="c",
    )


def test_prune_removes_only_expired_grants():
    conn, bus = _setup()
    _grant(bus, "developer", "feature", 1, 100)    # expires before now=200 -> expired
    _grant(bus, "developer", "bugfix", 1, 1000)    # still valid at now=200
    assert conn.execute("SELECT count(*) FROM proj_trust_grants").fetchone()[0] == 2

    n = prune_expired_trust_grants(conn, bus, "operator", "tidy expired", now_millis=lambda: 200)

    assert n == 1
    assert conn.execute("SELECT role_name, task_class FROM proj_trust_grants").fetchall() == [("developer", "bugfix")]


def test_prune_by_pk_spares_a_same_millisecond_sibling():
    # two grants share the natural key (role, class, granted_at) — one expired, one still valid. The fix
    # deletes by grant_row_id (PK), so only the expired one goes; a natural-key DELETE would drop BOTH.
    conn, bus = _setup()
    _grant(bus, "developer", "feature", 5, 10)     # row 1: expired at now=200
    _grant(bus, "developer", "feature", 5, 1000)   # row 2: same (role,class,granted_at), still valid
    assert conn.execute("SELECT count(*) FROM proj_trust_grants").fetchone()[0] == 2

    n = prune_expired_trust_grants(conn, bus, "operator", "tidy", now_millis=lambda: 200)

    assert n == 1
    assert conn.execute("SELECT grant_row_id, expires_at_millis FROM proj_trust_grants").fetchall() == [(2, 1000)]


def test_prune_requires_authorization_and_reason():
    conn, bus = _setup()
    _grant(bus, "developer", "feature", 1, 100)
    with pytest.raises(ValueError):
        prune_expired_trust_grants(conn, bus, "", "tidy", now_millis=lambda: 200)
    with pytest.raises(ValueError):
        prune_expired_trust_grants(conn, bus, "operator", "", now_millis=lambda: 200)
    assert conn.execute("SELECT count(*) FROM proj_trust_grants").fetchone()[0] == 1  # nothing pruned


def test_pruned_grant_stays_deleted_on_replay():
    # Inv 8: the trust_grant_pruned event follows trust_granted in the log, so a DELETE+replay of all
    # handlers reproduces the deletion (the row does not resurrect).
    conn, bus = _setup()
    _grant(bus, "developer", "feature", 1, 100)
    prune_expired_trust_grants(conn, bus, "operator", "tidy", now_millis=lambda: 200)
    assert conn.execute("SELECT count(*) FROM proj_trust_grants").fetchone()[0] == 0

    conn.execute("DELETE FROM proj_trust_grants")
    for et, payload, cid in conn.execute("SELECT event_type, payload, correlation_id FROM events ORDER BY seq"):
        if et in HANDLERS:
            HANDLERS[et](conn, {"payload": payload, "correlation_id": cid})

    assert conn.execute("SELECT count(*) FROM proj_trust_grants").fetchone()[0] == 0


def test_whitespace_authorization_is_refused():
    conn, bus = _setup()
    with pytest.raises(ValueError):
        prune_expired_trust_grants(conn, bus, "   ", "tidy")     # blank authorized_by
    with pytest.raises(ValueError):
        prune_expired_trust_grants(conn, bus, "operator", "  ")  # blank reason
