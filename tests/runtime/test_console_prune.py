"""Operator console prune action: authorize the removal of EXPIRED trust grants (the §S6 delete path).

The console holds the §S6 operator-authorized prune with a human in the seat (no LLM agent):
``list_expired`` surfaces the expired trust grants an authorized prune would remove (SELECT-only), and
``prune`` presses the SAME removal the ``devharness prune`` CLI drives, through the canonical
``maintenance.prune.prune_expired_trust_grants`` operation. Each removal is recorded as one
operator-attributed ``trust_grant_pruned`` event via ``EventBus.emit_sync`` — the console writes no event
store or projection directly — and only expired, non-revoked grants are ever touched; a blank
authorization reason is refused.
"""

import json
import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console import ConsolePrune
from devharness.console.app import ConsoleApp
from devharness.console.prune import EmptyPruneReason
from devharness.events.registry import TrustGranted


def _app():
    """A console connected to a fresh in-memory event store (migrated)."""
    return ConsoleApp(db_path=":memory:").connect()


def _grant(app, role, cls, granted_at, expires_at, *, correlation_id="c"):
    """Emit a trust_granted event through the bus (the canonical feed → proj_trust_grants)."""
    app.writer.emit_sync(
        "trust_granted",
        msgspec.to_builtins(TrustGranted(
            role_name=role, task_class=cls, brier_at_grant=0.1, granted_at_millis=granted_at,
            expires_at_millis=expires_at, granted_by="calibration", correlation_id=correlation_id)),
        correlation_id=correlation_id,
    )


def _events(conn, event_type):
    return [
        json.loads(payload)
        for (payload,) in conn.execute(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY seq", (event_type,)
        )
    ]


def _grant_count(conn):
    return conn.execute("SELECT COUNT(*) FROM proj_trust_grants").fetchone()[0]


def test_prune_returns_bound_action():
    app = _app()
    assert isinstance(app.prune(operator="ada"), ConsolePrune)


def test_list_expired_surfaces_only_expired_grants_select_only():
    app = _app()
    _grant(app, "developer", "feature", 1, 100)    # expired before now
    _grant(app, "developer", "bugfix", 1, 1000)    # still valid
    before = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    rows = ConsolePrune(app.conn, app.writer, operator="ada", now_millis=lambda: 200).list_expired()
    # only the expired grant; no event written by the read
    assert [(r[1], r[2]) for r in rows] == [("developer", "feature")]
    assert app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before


def test_prune_removes_only_expired_grants():
    app = _app()
    _grant(app, "developer", "feature", 1, 100)    # expired at now=200
    _grant(app, "developer", "bugfix", 1, 1000)    # still valid
    assert _grant_count(app.conn) == 2

    n = ConsolePrune(app.conn, app.writer, operator="ada", now_millis=lambda: 200).prune("tidy expired")

    assert n == 1
    assert app.conn.execute("SELECT role_name, task_class FROM proj_trust_grants").fetchall() == [
        ("developer", "bugfix")
    ]


def test_prune_records_operator_attributed_events():
    app = _app()
    _grant(app, "developer", "feature", 1, 100)
    ConsolePrune(app.conn, app.writer, operator="ada", now_millis=lambda: 200).prune("tidy expired")

    pruned = _events(app.conn, "trust_grant_pruned")
    assert len(pruned) == 1
    # the operator is the pruned_by authorizer (the human in the seat, not an LLM), with the reason
    assert pruned[0]["pruned_by"] == "ada"
    assert pruned[0]["reason"] == "tidy expired"
    assert pruned[0]["role_name"] == "developer"
    assert pruned[0]["task_class"] == "feature"


def test_prune_issues_the_same_operation_as_the_prune_cli():
    """The console prune and `devharness prune --confirm` reach the same canonical operation.

    Both delete every expired grant via one trust_grant_pruned event apiece; the console only differs by
    the operator seat in front of it (operator attribution, emit-only bus).
    """
    app = _app()
    _grant(app, "developer", "feature", 5, 10)     # expired
    _grant(app, "developer", "feature", 5, 1000)   # same natural key, still valid
    n = ConsolePrune(app.conn, app.writer, operator="ada", now_millis=lambda: 200).prune("tidy")
    # prune-by-PK spares the same-millisecond sibling — the canonical operation's behaviour, unchanged
    assert n == 1
    assert app.conn.execute(
        "SELECT grant_row_id, expires_at_millis FROM proj_trust_grants"
    ).fetchall() == [(2, 1000)]


def test_prune_requires_a_reason():
    app = _app()
    _grant(app, "developer", "feature", 1, 100)
    with pytest.raises(EmptyPruneReason):
        app.prune(operator="ada").prune("   ")
    # the refusal recorded nothing and pruned nothing — a reasonless authorization is not a delete
    assert _events(app.conn, "trust_grant_pruned") == []
    assert _grant_count(app.conn) == 1


def test_prune_with_no_expired_grants_is_a_noop():
    app = _app()
    _grant(app, "developer", "feature", 1, 1000)   # still valid at now=200
    n = ConsolePrune(app.conn, app.writer, operator="ada", now_millis=lambda: 200).prune("tidy")
    assert n == 0
    assert _events(app.conn, "trust_grant_pruned") == []
    assert _grant_count(app.conn) == 1


def test_per_call_operator_overrides_instance_default():
    app = _app()
    _grant(app, "developer", "feature", 1, 100)
    ConsolePrune(app.conn, app.writer, operator="ada", now_millis=lambda: 200).prune(
        "tidy", operator="grace"
    )
    pruned = _events(app.conn, "trust_grant_pruned")
    assert pruned[0]["pruned_by"] == "grace"


def test_prune_goes_through_the_event_bus_not_a_raw_write():
    app = _app()
    _grant(app, "developer", "feature", 1, 100)
    _grant(app, "developer", "bugfix", 1, 100)
    before = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    ConsolePrune(app.conn, app.writer, operator="ada", now_millis=lambda: 200).prune("tidy")
    after = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    # exactly one trust_grant_pruned event per expired grant — the emit-only write path
    assert after == before + 2


def test_pruned_grant_stays_deleted_on_replay():
    # Inv 8: the trust_grant_pruned event follows trust_granted in the log, so a DELETE+replay of all
    # handlers reproduces the deletion (the row does not resurrect).
    from devharness.projections.handlers import HANDLERS

    app = _app()
    _grant(app, "developer", "feature", 1, 100)
    ConsolePrune(app.conn, app.writer, operator="ada", now_millis=lambda: 200).prune("tidy")
    assert _grant_count(app.conn) == 0

    app.conn.execute("DELETE FROM proj_trust_grants")
    for et, payload, cid in app.conn.execute(
        "SELECT event_type, payload, correlation_id FROM events ORDER BY seq"
    ):
        if et in HANDLERS:
            HANDLERS[et](app.conn, {"payload": payload, "correlation_id": cid})

    assert _grant_count(app.conn) == 0
