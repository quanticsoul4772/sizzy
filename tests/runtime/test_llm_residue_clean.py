"""B5.1: clean residue → LLM invoked (mocked); structured-output + core-gate filtering."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.retro.base import RetroContext
from devharness.retro.llm_residue import CORE_GATES, analyze_with_llm


def _ctx():
    return RetroContext(terminal_outcome_event={"task_id": "t1", "outcome": "completed"}, preceding_events=[],
                        calibration_snapshot={}, source_task_id="t1", correlation_id="c")


def test_core_gates_set():
    assert CORE_GATES == {"workflow_guard", "secret_guard", "scope_guard", "sandbox",
                          "write_lock_gate", "spec_signed_gate", "verifier_attached_gate"}


def test_valid_candidate_passes():
    def llm(system_prompt, ctx, tier):
        return [{"kind": "antibody_candidate", "pattern_text": "novel pattern", "signature_name": ""}]
    out = analyze_with_llm(_ctx(), llm_fn=llm)
    assert len(out) == 1 and out[0]["pattern_text"] == "novel pattern"


def test_core_gate_proposal_filtered():
    def llm(system_prompt, ctx, tier):
        return [
            {"kind": "gate_change_candidate", "target_gate": "secret_guard", "change_kind": "loosen"},  # core -> dropped
            {"kind": "gate_change_candidate", "target_gate": "cost_mode_gate", "change_kind": "loosen"},  # non-core -> kept
        ]
    out = analyze_with_llm(_ctx(), llm_fn=llm)
    assert [c["target_gate"] for c in out] == ["cost_mode_gate"]


def test_freeform_text_rejected():
    def llm(system_prompt, ctx, tier):
        return ["just some freeform text", {"kind": "not_a_candidate"}, {"kind": "antibody_candidate", "pattern_text": "ok"}]
    out = analyze_with_llm(_ctx(), llm_fn=llm)
    assert len(out) == 1 and out[0]["kind"] == "antibody_candidate"
