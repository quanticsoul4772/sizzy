"""B5.0: RetroRun event — declared fields + terminal_kind set; EVENT_TYPES 40."""

import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_retro_run_registered():
    assert "retro_run" in ev.EVENT_TYPES
    r = msgspec.convert(
        {"terminal_outcome_correlation_id": "c", "source_task_id": "t1", "terminal_kind": "rejected",
         "t0_matched_signatures": ["sig_a"], "llm_invoked": True, "candidates_emitted_count": 2,
         "candidate_kinds": ["antibody_candidate", "gate_change_candidate"], "retro_run_at_millis": 5, "correlation_id": "c"},
        ev.RetroRun,
    )
    assert r.terminal_kind == "rejected" and r.candidates_emitted_count == 2 and r.llm_invoked is True


def test_b5_0_stub_shape():
    r = ev.RetroRun(terminal_outcome_correlation_id="c", source_task_id="t1", terminal_kind="completed",
                    t0_matched_signatures=[], llm_invoked=False, candidates_emitted_count=0,
                    candidate_kinds=[], retro_run_at_millis=1, correlation_id="c")
    assert r.candidate_kinds == [] and r.llm_invoked is False


def test_event_types_count_at_least_40():
    assert len(ev.EVENT_TYPES) >= 40
