"""Gate-change enactment (§S7): an approved gate-change candidate actually takes effect.

Closes the asymmetry where the antibody half of the learning spine was live (approved → screened) but
the gate-change half dead-ended at "approved but inert". An approved gate-change is enacted into
proj_enacted_gate_changes and an enacted add_signature screens real diffs live. Inv 12 holds: a
core-gate weakening can never be enacted.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import msgspec
import pytest

from devharness.events.bus import EventBus
from devharness.events.registry import GateChangeCandidate
from devharness.gates.antibody_screen import AntibodyScreenGate
from devharness.gates.base import GateDeny, GateOk
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.approval import approve_gate_change_candidate
from devharness.retro.enacted_gate_changes import (
    enact_gate_change,
    enacted_changes_for_gate,
    enacted_signature_patterns,
)


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _emit_candidate(bus, *, target_gate, change_kind, change_details, cid="r1"):
    bus.emit_sync(
        "gate_change_candidate",
        msgspec.to_builtins(GateChangeCandidate(
            retro_run_correlation_id=cid, signature_name="sig", target_gate=target_gate,
            change_kind=change_kind, change_details=change_details, evidence_event_ids=[],
            source="t0", created_at_millis=1, correlation_id=cid)),
        correlation_id=cid,
    )


def test_approve_marks_approved_and_enacts():
    conn, bus = _setup()
    _emit_candidate(bus, target_gate="antibody_screen", change_kind="add_signature",
                    change_details={"signature": "evil_backdoor_marker"})
    row_id = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue").fetchone()[0]

    enacted_id = approve_gate_change_candidate(row_id, "operator", conn, bus, now_millis=lambda: 9)

    assert isinstance(enacted_id, int)
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE gate_change_row_id=?",
                        (row_id,)).fetchone()[0] == "approved"
    assert conn.execute("SELECT count(*) FROM proj_enacted_gate_changes").fetchone()[0] == 1
    assert enacted_changes_for_gate("antibody_screen", conn) == [
        {"change_kind": "add_signature", "change_details": {"signature": "evil_backdoor_marker"}}]
    assert enacted_signature_patterns("antibody_screen", conn) == ["evil_backdoor_marker"]


def test_advisory_kind_is_approved_but_not_auto_enacted():
    # the deterministic spine's actual output (tighten on verifier_attached_gate) has no auto-applicable
    # parameter -> approving it marks approved but enacts NOTHING, so proj_enacted_gate_changes holds only
    # what is in effect (never an inert row).
    conn, bus = _setup()
    _emit_candidate(bus, target_gate="verifier_attached_gate", change_kind="tighten",
                    change_details={"axis": "test_suite"})
    row_id = conn.execute(
        "SELECT gate_change_row_id FROM proj_gate_change_queue WHERE review_state='pending'").fetchone()[0]

    enacted_id = approve_gate_change_candidate(row_id, "operator", conn, bus)

    assert enacted_id is None  # approved, but nothing auto-applicable to enact
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE gate_change_row_id=?",
                        (row_id,)).fetchone()[0] == "approved"
    assert conn.execute("SELECT count(*) FROM proj_enacted_gate_changes").fetchone()[0] == 0


def test_enacted_add_signature_is_live_in_the_screen():
    conn, bus = _setup()
    _emit_candidate(bus, target_gate="antibody_screen", change_kind="add_signature",
                    change_details={"signature": "evil_backdoor_marker"})
    row_id = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue").fetchone()[0]
    diff = "+++ b/x.py\n+    do_thing()  # evil_backdoor_marker\n"

    # before approval the pattern is inert — the screen passes it
    assert isinstance(AntibodyScreenGate().check({"conn": conn, "diff_content": diff}), GateOk)

    approve_gate_change_candidate(row_id, "operator", conn, bus)

    # after approval the enacted gate-change screens it live (the whole point — no longer inert)
    result = AntibodyScreenGate().check({"conn": conn, "diff_content": diff})
    assert isinstance(result, GateDeny)
    assert "evil_backdoor_marker" in str(result.reason)


def test_core_gate_weakening_cannot_be_enacted():
    conn, bus = _setup()
    # Inv 12 belt-and-suspenders: even a direct enact call refuses to weaken a core gate
    with pytest.raises(ValueError):
        enact_gate_change("scope_guard", "loosen", {}, "c1", "operator", conn, bus)
    assert conn.execute("SELECT count(*) FROM proj_enacted_gate_changes").fetchone()[0] == 0


def test_enacted_row_rebuilds_from_its_event():
    # Inv 8: the gate_change_enacted event carries the explicit enacted_row_id, so a DELETE+replay of the
    # handler reproduces the projection row byte-for-byte.
    conn, bus = _setup()
    _emit_candidate(bus, target_gate="antibody_screen", change_kind="add_signature",
                    change_details={"signature": "p_marker"})
    row_id = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue").fetchone()[0]
    approve_gate_change_candidate(row_id, "operator", conn, bus)
    before = conn.execute("SELECT * FROM proj_enacted_gate_changes").fetchall()

    from devharness.projections.handlers import handle_gate_change_enacted
    conn.execute("DELETE FROM proj_enacted_gate_changes")
    for payload, cid in conn.execute(
            "SELECT payload, correlation_id FROM events WHERE event_type='gate_change_enacted' ORDER BY seq"):
        handle_gate_change_enacted(conn, {"payload": payload, "correlation_id": cid})

    assert conn.execute("SELECT * FROM proj_enacted_gate_changes").fetchall() == before
