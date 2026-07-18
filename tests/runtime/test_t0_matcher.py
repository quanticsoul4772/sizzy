"""B5.1: T0 pattern-matcher — signatures match their terminal-context shape; single-write registry."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.retro.base import RetroContext
from devharness.retro.t0_matcher import (
    PATTERN_SIGNATURES,
    SignatureRegistrationError,
    SignatureSpec,
    match_signatures,
    register_signature,
)


def _ctx(preceding, calibration=None):
    return RetroContext(terminal_outcome_event={"task_id": "t1", "outcome": "rejected"}, preceding_events=preceding,
                        calibration_snapshot=calibration or {}, source_task_id="t1", correlation_id="c")


def _gate_fired(gate, reason=""):
    return {"event_id": "e1", "event_type": "gate_fired", "payload": {"gate": gate, "decision": "deny", "reason": reason}}


def test_gate_deny_signatures_match():
    m = match_signatures(_ctx([_gate_fired("workflow_guard")]))
    assert any(x.signature_name == "gate_deny_workflow_modified" and x.candidate_kind == "antibody_candidate" for x in m)


def test_secret_axes_distinguished():
    path = match_signatures(_ctx([_gate_fired("secret_guard", "secret_detected: axes path")]))
    assert {x.signature_name for x in path} == {"gate_deny_secret_path"}
    content = match_signatures(_ctx([_gate_fired("secret_guard", "secret_detected: axes content")]))
    assert {x.signature_name for x in content} == {"gate_deny_secret_content"}


def test_intake_rejection_signature():
    ev = {"event_id": "e2", "event_type": "intake_decision", "payload": {"decision": "rejected", "rejection_reason": "license_disallowed"}}
    m = match_signatures(_ctx([ev]))
    assert any(x.signature_name == "intake_reject_license" for x in m)


def test_calibration_drift_signature():
    assert any(x.signature_name == "calibration_brier_drift" for x in match_signatures(_ctx([], {"brier": 0.3})))
    assert not any(x.signature_name == "calibration_brier_drift" for x in match_signatures(_ctx([], {"brier": 0.1})))


def test_cap_exceeded_signature():
    ev = {"event_id": "e3", "event_type": "budget_exceeded", "payload": {"budget_kind": "oss_wall_clock", "action_taken": "abort"}}
    m = match_signatures(_ctx([ev]))
    assert any(x.signature_name == "cap_exceeded_wall_clock" and x.candidate_kind == "gate_change_candidate" for x in m)


def test_no_match_on_clean_context():
    assert match_signatures(_ctx([{"event_id": "e", "event_type": "task_started", "payload": {}}])) == []


def test_single_write_registry():
    with pytest.raises(SignatureRegistrationError):
        register_signature(SignatureSpec(signature_name="gate_deny_workflow_modified", match_predicate_ref="x",
                                         candidate_kind="antibody_candidate", candidate_payload_template={}))
