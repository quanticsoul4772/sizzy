"""Operator console gate-change enactment action: enact an APPROVED gate-change candidate (§S7).

The console holds the §S7 gate-change enactment with a human in the seat (no LLM agent): ``enact``
issues the SAME operation as the canonical gate-change enactment path
(``retro.enacted_gate_changes.enact_gate_change``). The enactment is recorded as the
operator-attributed ``gate_change_enacted`` event via ``EventBus.emit_sync`` — the console writes no
event store or projection directly — and because the canonical operation is used unchanged,
**Invariant 12 still refuses any core-gate weakening** and a non-auto-applicable change is refused
before any event is emitted. Only an operator-approved candidate may be enacted.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console import ConsoleEnactGateChange, GateChangeNotApproved
from devharness.console.app import ConsoleApp
from devharness.console.enact_gate_change import CandidateNotFound


def _app():
    """A console connected to a fresh in-memory event store (migrated)."""
    return ConsoleApp(db_path=":memory:").connect()


def _seed_gate_change(app, *, target_gate="antibody_screen", change_kind="add_signature",
                      change_details=None, correlation_id="c", created_at=2):
    """Emit one gate-change CANDIDATE through the bus (the canonical feed); return its assigned row id.

    Defaults to an auto-applicable ``add_signature`` (the only ``is_enactable`` change today). The
    projection inserts it ``pending`` — no auto-apply (SC-2).
    """
    if change_details is None:
        change_details = {"signature": "leak the token"}
    app.writer.emit_sync(
        "gate_change_candidate",
        {"retro_run_correlation_id": correlation_id, "signature_name": "sig",
         "target_gate": target_gate, "change_kind": change_kind, "change_details": change_details,
         "evidence_event_ids": [], "source": "t0", "created_at_millis": created_at},
        correlation_id=correlation_id,
    )
    return app.conn.execute("SELECT MAX(gate_change_row_id) FROM proj_gate_change_queue").fetchone()[0]


def _approve(app, gc, *, reviewed_by="ada", correlation_id="c", at=3):
    """Mark a gate-change candidate ``approved`` via the operator-review transition (no auto-enact here)."""
    app.writer.emit_sync(
        "candidate_reviewed",
        {"candidate_row_id": gc, "candidate_kind": "gate_change_candidate", "review_state": "approved",
         "reviewed_by": reviewed_by, "review_reason": "", "reviewed_at_millis": at,
         "correlation_id": correlation_id},
        correlation_id=correlation_id,
    )


def _events(conn, event_type):
    return [
        json.loads(payload)
        for (payload,) in conn.execute(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY seq", (event_type,)
        )
    ]


def test_enact_gate_change_returns_bound_action():
    app = _app()
    assert isinstance(app.enact_gate_change(operator="ada"), ConsoleEnactGateChange)


def test_list_approved_surfaces_only_approved_candidates_with_enactable_flag():
    app = _app()
    approved = _seed_gate_change(app)               # add_signature → enactable
    _seed_gate_change(app, target_gate="cost_mode_gate", change_kind="loosen", change_details={})  # pending
    _approve(app, approved)

    rows = app.enact_gate_change(operator="ada").list_approved()
    assert [r["gate_change_row_id"] for r in rows] == [approved]
    assert rows[0]["enactable"] is True
    assert rows[0]["target_gate"] == "antibody_screen"
    assert rows[0]["change_details"] == {"signature": "leak the token"}


def test_list_approved_marks_an_advisory_change_not_enactable():
    app = _app()
    gc = _seed_gate_change(app, target_gate="cost_mode_gate", change_kind="loosen", change_details={})
    _approve(app, gc)
    rows = app.enact_gate_change(operator="ada").list_approved()
    assert rows[0]["gate_change_row_id"] == gc
    assert rows[0]["enactable"] is False


def test_enact_records_an_operator_attributed_event():
    app = _app()
    gc = _seed_gate_change(app)
    _approve(app, gc)
    app.enact_gate_change(operator="ada").enact(gc)

    enacted = _events(app.conn, "gate_change_enacted")
    assert len(enacted) == 1
    e = enacted[0]
    assert e["enacted_by"] == "ada"            # the operator (human in the seat), not the approver
    assert e["target_gate"] == "antibody_screen"
    assert e["change_kind"] == "add_signature"
    assert e["change_details"] == {"signature": "leak the token"}
    assert e["source_candidate_id"] == str(gc)


def test_enact_writes_into_the_enacted_gate_change_projection():
    app = _app()
    gc = _seed_gate_change(app)
    _approve(app, gc)
    enacted_row_id = app.enact_gate_change(operator="ada").enact(gc)

    assert isinstance(enacted_row_id, int)
    row = app.conn.execute(
        "SELECT target_gate, change_kind, enacted_by FROM proj_enacted_gate_changes "
        "WHERE enacted_row_id = ?", (enacted_row_id,)
    ).fetchone()
    assert row == ("antibody_screen", "add_signature", "ada")


def test_per_call_operator_overrides_instance_default():
    app = _app()
    gc = _seed_gate_change(app)
    _approve(app, gc)
    app.enact_gate_change(operator="ada").enact(gc, operator="grace")
    assert _events(app.conn, "gate_change_enacted")[0]["enacted_by"] == "grace"


def test_now_millis_seam_stamps_the_enactment():
    app = _app()
    gc = _seed_gate_change(app)
    _approve(app, gc)
    action = ConsoleEnactGateChange(app.conn, app.writer, operator="ada", now_millis=lambda: 9999)
    action.enact(gc)
    assert _events(app.conn, "gate_change_enacted")[0]["enacted_at_millis"] == 9999


def test_enact_refuses_a_not_approved_candidate():
    app = _app()
    gc = _seed_gate_change(app)  # left pending — never approved
    with pytest.raises(GateChangeNotApproved):
        app.enact_gate_change(operator="ada").enact(gc)
    # the refusal recorded nothing — a not-approved candidate is never enacted
    assert _events(app.conn, "gate_change_enacted") == []


def test_enact_refuses_an_unknown_candidate():
    app = _app()
    with pytest.raises(CandidateNotFound):
        app.enact_gate_change(operator="ada").enact(999)


def test_enact_refuses_a_core_gate_weakening_inv12():
    app = _app()
    # a core-gate weakening (Inv 12) — auto-rejected at creation in the live spine, but a hand-built
    # approved row must STILL be refused at the enactment surface (belt-and-suspenders).
    gc = _seed_gate_change(app, target_gate="scope_guard", change_kind="loosen", change_details={})
    _approve(app, gc)
    with pytest.raises(ValueError):
        app.enact_gate_change(operator="ada").enact(gc)
    assert _events(app.conn, "gate_change_enacted") == []


def test_enact_refuses_a_non_auto_applicable_change():
    app = _app()
    # approved-but-advisory (a `loosen` on a non-core gate has no auto-applicable parameter)
    gc = _seed_gate_change(app, target_gate="cost_mode_gate", change_kind="loosen", change_details={})
    _approve(app, gc)
    with pytest.raises(ValueError):
        app.enact_gate_change(operator="ada").enact(gc)
    assert _events(app.conn, "gate_change_enacted") == []


def test_enact_goes_through_the_event_bus_not_a_raw_write():
    app = _app()
    gc = _seed_gate_change(app)
    _approve(app, gc)
    before = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    app.enact_gate_change(operator="ada").enact(gc)
    after = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    # the enact appends exactly the one gate_change_enacted event
    assert after == before + 1
