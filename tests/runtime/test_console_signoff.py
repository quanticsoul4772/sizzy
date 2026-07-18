"""Operator console sign-off action: review the synthesized spec and sign or reject it.

The console holds the operator sign-off gate with a human in the seat (no LLM agent):
``sign`` routes through the canonical sign path so the ``spec_signed_gate`` (Invariant 4 /
commitment 12) is preserved exactly, and ``reject`` records an operator-attributed refusal
that leaves the spec unsigned (the gate keeps refusing). Both decisions are recorded
through ``EventBus.emit_sync`` — the console writes no event store or projection directly.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cli.sign import UnknownSpec
from devharness.console import ConsoleSignoff, EmptyRejectionReason, SPEC_REJECTED_EVENT
from devharness.console.app import ConsoleApp
from devharness.gates.base import GateDeny, GateOk
from devharness.gates.spec_signed import SpecSignedGate


def _app():
    """A console connected to a fresh in-memory event store (migrated)."""
    return ConsoleApp(db_path=":memory:").connect()


_SPEC_PAYLOAD = {
    "problem": "a stdlib repo-consistency checker",
    "scope": "scan the repo and report drift",
    "non_goals": ["fixing drift automatically"],
    "interfaces": ["python -m specledger"],
    "success_criteria": ["reports every inconsistency"],
    "verification_plan": "unit tests over fixture repos",
    "assumptions": [
        {"text": "stdlib only", "confidence": 0.9, "low_confidence_flag": False}
    ],
    "correlation_id": "proj-1",
}


def _seed_spec(conn, *, spec_id="spec-1", correlation_id="proj-1", payload=None):
    """Insert an unsigned spec artifact the way the research role's storage does."""
    body = dict(payload or _SPEC_PAYLOAD)
    body["correlation_id"] = correlation_id
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, ?, ?, ?, 0)",
        (spec_id, json.dumps(body), correlation_id, 100),
    )
    conn.commit()
    return spec_id


def _events(conn, event_type):
    return [
        json.loads(payload)
        for (payload,) in conn.execute(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY seq", (event_type,)
        )
    ]


def _gate_result(conn, correlation_id):
    return SpecSignedGate().check({"conn": conn, "correlation_id": correlation_id})


def test_signoff_returns_bound_action():
    app = _app()
    assert isinstance(app.signoff(operator="ada"), ConsoleSignoff)


def test_review_surfaces_the_spec_for_the_operator():
    app = _app()
    _seed_spec(app.conn)
    payload = app.signoff(operator="ada").review("spec-1")
    assert payload["problem"] == "a stdlib repo-consistency checker"
    assert payload["correlation_id"] == "proj-1"


def test_review_refuses_unknown_spec():
    app = _app()
    with pytest.raises(UnknownSpec):
        app.signoff(operator="ada").review("nope")


def test_gate_denies_before_sign_off():
    app = _app()
    _seed_spec(app.conn)
    # the human sign-off gate refuses an unsigned spec
    assert isinstance(_gate_result(app.conn, "proj-1"), GateDeny)


def test_sign_preserves_the_human_sign_off_gate():
    app = _app()
    _seed_spec(app.conn)

    spec_id = app.signoff(operator="ada").sign("spec-1")
    assert spec_id == "spec-1"

    # the canonical gate (Invariant 4 / commitment 12) now admits the build
    assert isinstance(_gate_result(app.conn, "proj-1"), GateOk)


def test_sign_records_an_operator_attributed_event():
    app = _app()
    _seed_spec(app.conn)
    app.signoff(operator="ada").sign("spec-1")

    signed = _events(app.conn, "spec_signed")
    assert len(signed) == 1
    assert signed[0]["spec_id"] == "spec-1"
    # the operator is the attributed signer (the human in the seat, not an LLM)
    assert signed[0]["signer"] == "ada"


def test_sign_flips_the_signed_spec_projection():
    app = _app()
    _seed_spec(app.conn)
    app.signoff(operator="ada").sign("spec-1")

    state = app.loop_state()
    assert state.spec_signed is True
    assert state.signed_spec_id == "spec-1"
    assert state.signed_by == "ada"


def test_sign_refuses_unknown_spec():
    app = _app()
    with pytest.raises(UnknownSpec):
        app.signoff(operator="ada").sign("nope")


def test_reject_leaves_the_gate_refusing():
    app = _app()
    _seed_spec(app.conn)

    spec_id = app.signoff(operator="ada").reject("spec-1", "scope is too broad")
    assert spec_id == "spec-1"

    # rejection records the decision but does NOT sign — the gate keeps refusing
    assert isinstance(_gate_result(app.conn, "proj-1"), GateDeny)
    assert app.loop_state().spec_signed is False


def test_reject_records_an_operator_attributed_event():
    app = _app()
    _seed_spec(app.conn)
    app.signoff(operator="ada").reject("spec-1", "scope is too broad")

    rejected = _events(app.conn, SPEC_REJECTED_EVENT)
    assert len(rejected) == 1
    assert rejected[0]["spec_id"] == "spec-1"
    assert rejected[0]["operator"] == "ada"
    assert rejected[0]["reason"] == "scope is too broad"
    assert "rejected_at_millis" in rejected[0]


def test_reject_uses_the_spec_correlation_id():
    app = _app()
    _seed_spec(app.conn, spec_id="spec-x", correlation_id="proj-x")
    app.signoff(operator="ada").reject("spec-x", "needs a non-goal")

    row = app.conn.execute(
        "SELECT correlation_id FROM events WHERE event_type = ?", (SPEC_REJECTED_EVENT,)
    ).fetchone()
    assert row[0] == "proj-x"


def test_reject_refuses_unknown_spec():
    app = _app()
    with pytest.raises(UnknownSpec):
        app.signoff(operator="ada").reject("nope", "a reason")


def test_reject_requires_a_reason():
    app = _app()
    _seed_spec(app.conn)
    with pytest.raises(EmptyRejectionReason):
        app.signoff(operator="ada").reject("spec-1", "   ")
    # the refusal recorded nothing — a reasonless rejection is not an event
    assert _events(app.conn, SPEC_REJECTED_EVENT) == []


def test_per_call_operator_overrides_instance_default():
    app = _app()
    _seed_spec(app.conn)
    app.signoff(operator="ada").sign("spec-1", operator="grace")
    assert _events(app.conn, "spec_signed")[0]["signer"] == "grace"


def test_now_millis_seam_stamps_the_rejection():
    app = _app()
    _seed_spec(app.conn)
    signoff = ConsoleSignoff(app.conn, app.writer, operator="ada", now_millis=lambda: 4242)
    signoff.reject("spec-1", "scope is too broad")
    assert _events(app.conn, SPEC_REJECTED_EVENT)[0]["rejected_at_millis"] == 4242


def test_decision_goes_through_the_event_bus_not_a_raw_write():
    app = _app()
    _seed_spec(app.conn)
    before = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    app.signoff(operator="ada").reject("spec-1", "scope is too broad")
    after = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    # exactly one event appended (the operator decision), via EventBus.emit_sync
    assert after == before + 1
