"""Operator console retro-review action: approve or reject a retro CANDIDATE at the §S7 review.

The console holds the §S7 operator review with a human in the seat (no LLM agent): ``approve`` /
``reject`` press the SAME approve/reject decision the ``devharness retro approve/reject`` CLI drives,
in the CLI's own vocabulary, through the canonical ``retro.approval`` operation. The decision is
recorded as the operator-attributed ``candidate_reviewed`` event via ``EventBus.emit_sync`` — the
console writes no event store or projection directly — and SC-2 (no auto-apply), Inv 11, and Inv 12 are
preserved because the canonical operation is used unchanged (``ConsoleRetro`` is a thin CLI-vocabulary
surface over the shared ``ConsoleTaskDecision`` review logic).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console import ConsoleRetro
from devharness.console.app import ConsoleApp
from devharness.console.retro import CandidateNotFound, EmptyRejectionReason, UnknownQueue


def _app():
    """A console connected to a fresh in-memory event store (migrated)."""
    return ConsoleApp(db_path=":memory:").connect()


def _seed_candidates(app, *, correlation_id="c"):
    """Emit one antibody + one gate-change CANDIDATE through the bus (the canonical feed).

    Returns the (antibody_row_id, gate_change_row_id) the queue projections assigned.
    """
    app.writer.emit_sync(
        "antibody_candidate",
        {"retro_run_correlation_id": correlation_id, "signature_name": "sig_a",
         "pattern_text": "leak the token", "evidence_event_ids": [], "source": "t0",
         "created_at_millis": 1},
        correlation_id=correlation_id,
    )
    app.writer.emit_sync(
        "gate_change_candidate",
        {"retro_run_correlation_id": correlation_id, "signature_name": "sig_b",
         "target_gate": "cost_mode_gate", "change_kind": "loosen", "change_details": {},
         "evidence_event_ids": [], "source": "t0", "created_at_millis": 2},
        correlation_id=correlation_id,
    )
    ab = app.conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    gc = app.conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue").fetchone()[0]
    return ab, gc


def _events(conn, event_type):
    return [
        json.loads(payload)
        for (payload,) in conn.execute(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY seq", (event_type,)
        )
    ]


def test_retro_returns_bound_action():
    app = _app()
    assert isinstance(app.retro(operator="ada"), ConsoleRetro)


def test_list_pending_surfaces_both_queues():
    app = _app()
    _seed_candidates(app)
    rows = app.retro(operator="ada").list_pending(queue="all")
    assert {r["queue"] for r in rows} == {"antibody", "gate-change"}
    assert app.retro().list_pending(queue="antibody")[0]["detail"] == "leak the token"


def test_approve_approves_the_antibody_candidate():
    app = _app()
    ab, _ = _seed_candidates(app)
    app.retro(operator="ada").approve("antibody", ab)
    # the queue row is approved and attributed to the operator (the human in the seat, not an LLM)
    row = app.conn.execute(
        "SELECT review_state, reviewed_by FROM proj_antibody_queue WHERE antibody_row_id = ?", (ab,)
    ).fetchone()
    assert row == ("approved", "ada")


def test_approve_publishes_the_antibody_into_the_active_library():
    app = _app()
    ab, _ = _seed_candidates(app)
    new_id = app.retro(operator="ada").approve("antibody", ab)
    # approve returns the published antibody row id and the pattern is now active
    assert isinstance(new_id, int)
    active = app.conn.execute(
        "SELECT pattern_text FROM proj_antibody_library WHERE antibody_row_id = ?", (new_id,)
    ).fetchone()
    assert active is not None
    assert active[0] == "leak the token"


def test_approve_records_an_operator_attributed_event():
    app = _app()
    ab, _ = _seed_candidates(app)
    app.retro(operator="ada").approve("antibody", ab)

    reviewed = [e for e in _events(app.conn, "candidate_reviewed") if e["candidate_row_id"] == ab]
    assert len(reviewed) == 1
    assert reviewed[0]["review_state"] == "approved"
    assert reviewed[0]["reviewed_by"] == "ada"
    assert reviewed[0]["candidate_kind"] == "antibody_candidate"


def test_reject_marks_the_candidate_rejected_with_operator_and_reason():
    app = _app()
    ab, _ = _seed_candidates(app)
    returned = app.retro(operator="ada").reject("antibody", ab, "false positive")
    assert returned == ab

    state = app.conn.execute(
        "SELECT review_state FROM proj_antibody_queue WHERE antibody_row_id = ?", (ab,)
    ).fetchone()[0]
    assert state == "rejected"

    reviewed = [e for e in _events(app.conn, "candidate_reviewed") if e["candidate_row_id"] == ab]
    assert reviewed[-1]["review_state"] == "rejected"
    assert reviewed[-1]["reviewed_by"] == "ada"
    assert reviewed[-1]["review_reason"] == "false positive"

    audit = [e for e in _events(app.conn, "candidate_rejected") if e["candidate_row_id"] == ab]
    assert len(audit) == 1
    assert audit[0]["rejected_by"] == "ada"
    assert audit[0]["reason"] == "false positive"


def test_reject_a_gate_change_candidate():
    app = _app()
    _, gc = _seed_candidates(app)
    app.retro(operator="ada").reject("gate-change", gc, "not worth tightening")
    state = app.conn.execute(
        "SELECT review_state FROM proj_gate_change_queue WHERE gate_change_row_id = ?", (gc,)
    ).fetchone()[0]
    assert state == "rejected"


def test_reject_requires_a_reason():
    app = _app()
    ab, _ = _seed_candidates(app)
    with pytest.raises(EmptyRejectionReason):
        app.retro(operator="ada").reject("antibody", ab, "   ")
    # the refusal recorded nothing — a reasonless rejection is not an event
    assert _events(app.conn, "candidate_reviewed") == []
    # and the candidate is still pending
    state = app.conn.execute(
        "SELECT review_state FROM proj_antibody_queue WHERE antibody_row_id = ?", (ab,)
    ).fetchone()[0]
    assert state == "pending"


def test_unknown_queue_is_refused():
    app = _app()
    with pytest.raises(UnknownQueue):
        app.retro(operator="ada").approve("nope", 1)
    with pytest.raises(UnknownQueue):
        app.retro(operator="ada").reject("nope", 1, "a reason")


def test_unknown_candidate_is_refused():
    app = _app()
    with pytest.raises(CandidateNotFound):
        app.retro(operator="ada").approve("antibody", 999)


def test_per_call_operator_overrides_instance_default():
    app = _app()
    ab, _ = _seed_candidates(app)
    app.retro(operator="ada").approve("antibody", ab, operator="grace")
    reviewed = [e for e in _events(app.conn, "candidate_reviewed") if e["candidate_row_id"] == ab]
    assert reviewed[0]["reviewed_by"] == "grace"


def test_now_millis_seam_stamps_the_decision():
    app = _app()
    ab, _ = _seed_candidates(app)
    action = ConsoleRetro(app.conn, app.writer, operator="ada", now_millis=lambda: 4242)
    action.reject("antibody", ab, "false positive")
    reviewed = [e for e in _events(app.conn, "candidate_reviewed") if e["candidate_row_id"] == ab]
    assert reviewed[-1]["reviewed_at_millis"] == 4242


def test_decision_goes_through_the_event_bus_not_a_raw_write():
    app = _app()
    ab, _ = _seed_candidates(app)
    before = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    app.retro(operator="ada").reject("antibody", ab, "false positive")
    after = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    # the reject appends exactly the two operator-decision events (reviewed + rejected audit)
    assert after == before + 2


def test_approve_issues_the_same_operation_as_the_retro_cli():
    """The console approve and `devharness retro approve` reach the same canonical retro.approval path.

    Both publish the antibody into the active library (source_candidate_id = the queue row) and record an
    approved candidate_reviewed event; the console only differs by the operator seat in front of it
    (operator attribution, emit-only bus).
    """
    app = _app()
    ab, _ = _seed_candidates(app)
    new_id = app.retro(operator="ada").approve("antibody", ab)
    # same effect the CLI's approve_antibody_candidate produces: a published, active antibody row
    active = app.conn.execute(
        "SELECT source_candidate_id FROM proj_antibody_library WHERE antibody_row_id = ?", (new_id,)
    ).fetchone()
    assert active is not None
    assert active[0] == str(ab)
