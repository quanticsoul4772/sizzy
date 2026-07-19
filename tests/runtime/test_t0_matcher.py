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


def _verifier_ev(verifier, detail, task_id="t1", passed=False):
    return {"event_id": "ev1", "event_type": "verifier_outcome",
            "payload": {"task_id": task_id, "verifier": verifier, "passed": passed, "detail": detail}}


def test_verifier_failure_signatures_fire_on_structured_axis():
    m = match_signatures(_ctx([_verifier_ev(
        "bugfix_regression", "baseline_should_fail axis failed: the regression test passed at baseline (no bug demonstrated)")]))
    assert {x.signature_name for x in m} == {"verifier_failure_baseline_fail"}
    m = match_signatures(_ctx([_verifier_ev(
        "bugfix_regression", "post_should_pass axis failed: the regression test still fails after the fix")]))
    assert {x.signature_name for x in m} == {"verifier_failure_post_pass"}
    for axis in ("test_added", "test_removed", "pass_to_fail", "fail_to_pass"):
        m = match_signatures(_ctx([_verifier_ev(
            "refactor_behavior_preserving", f"{axis} axis failed: refactor changed the test pass/fail set for ['tests/test_x.py::t']")]))
        assert {x.signature_name for x in m} == {"verifier_failure_behavior_change"}, axis


def test_verifier_failure_ignores_output_tail_tokens():
    # the verlite/wordstat false positive (rev 0.4.23): a pytest-asyncio warning in the appended output
    # tail contains "unexpected behavior"; the old substring scan fired verifier_failure_behavior_change
    # on a dependency_resolves / feature_spec_claim failure. The axis-prefix match must stay silent.
    tail = ("suite_passes axis failed: test command exited 1 — output tail:\n"
            "Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future.\n"
            "baseline post behavior")
    assert match_signatures(_ctx([_verifier_ev("dependency_resolves", tail)])) == []
    assert match_signatures(_ctx([_verifier_ev(
        "feature_spec_claim", "test_suite axis failed: unexpected behavior in the post baseline")])) == []


def test_verifier_failure_requires_matching_task():
    # a plan's tasks share one correlation_id, so an earlier task's failed verifier_outcome sits in
    # every later terminal's preceding_events — it must not re-fire on another task's terminal
    ev = _verifier_ev("bugfix_regression",
                      "baseline_should_fail axis failed: the regression test passed at baseline", task_id="other-task")
    assert match_signatures(_ctx([ev])) == []


def test_verifier_failure_requires_failed_outcome():
    ev = _verifier_ev("bugfix_regression", "baseline_should_fail axis failed: …", passed=True)
    assert match_signatures(_ctx([ev])) == []


def test_verifier_failure_never_fires_on_a_completed_terminal():
    # review catch (rev 0.4.23): retro dedup is (task_id, terminal_kind), so a re-driven task's
    # COMPLETED terminal is re-analyzed with the first attempt's failed verifier_outcome still in
    # preceding_events and a MATCHING task_id — without this gate the signature re-fires a duplicate
    # candidate wrongly attributed to the success. Same for an intra-attempt corrected failure
    # (fail → auto-retry → pass): the loop working as designed is not a gate-tightening signal.
    ev = _verifier_ev("bugfix_regression",
                      "baseline_should_fail axis failed: the regression test passed at baseline")
    ctx = RetroContext(terminal_outcome_event={"task_id": "t1", "outcome": "completed"},
                       preceding_events=[ev], calibration_snapshot={},
                       source_task_id="t1", correlation_id="c")
    assert match_signatures(ctx) == []


def test_verifier_failure_empty_capture_not_behavior_change():
    # the refactor empty-capture reason is a runner-launch failure, not a behavior change — unsignatured
    ev = _verifier_ev("refactor_behavior_preserving",
                      "pass_fail_command produced no test results on either baseline or post — the test "
                      "runner did not run (cannot assert behaviour preserved against an empty test set)")
    assert match_signatures(_ctx([ev])) == []


def test_no_match_on_clean_context():
    assert match_signatures(_ctx([{"event_id": "e", "event_type": "task_started", "payload": {}}])) == []


def test_single_write_registry():
    with pytest.raises(SignatureRegistrationError):
        register_signature(SignatureSpec(signature_name="gate_deny_workflow_modified", match_predicate_ref="x",
                                         candidate_kind="antibody_candidate", candidate_payload_template={}))
