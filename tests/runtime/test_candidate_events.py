"""B5.1: AntibodyCandidate + GateChangeCandidate events; EVENT_TYPES 42."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_antibody_candidate_registered():
    assert "antibody_candidate" in ev.EVENT_TYPES
    a = ev.AntibodyCandidate(retro_run_correlation_id="c", signature_name="sig", pattern_text="known-bad",
                             evidence_event_ids=["e1"], source="t0", created_at_millis=1, correlation_id="c")
    assert a.candidate_kind == "antibody_candidate" and a.pattern_text == "known-bad"


def test_antibody_pattern_text_required():
    with pytest.raises(ValueError):
        ev.AntibodyCandidate(retro_run_correlation_id="c", signature_name="s", pattern_text="",
                             evidence_event_ids=[], source="t0", created_at_millis=1, correlation_id="c")


def test_gate_change_candidate_registered():
    assert "gate_change_candidate" in ev.EVENT_TYPES
    g = ev.GateChangeCandidate(retro_run_correlation_id="c", signature_name="sig", target_gate="cost_mode_gate",
                               change_kind="loosen", change_details={"x": 1}, evidence_event_ids=[], source="t0",
                               created_at_millis=1, correlation_id="c")
    assert g.candidate_kind == "gate_change_candidate" and g.change_kind == "loosen"


def test_candidate_kind_literal_validated():
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({"retro_run_correlation_id": "c", "signature_name": "s", "pattern_text": "x",
                         "evidence_event_ids": [], "source": "t0", "created_at_millis": 1, "correlation_id": "c",
                         "candidate_kind": "wrong"}, ev.AntibodyCandidate)


def test_change_kind_literal_validated():
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({"retro_run_correlation_id": "c", "signature_name": "s", "target_gate": "g",
                         "change_kind": "bogus", "change_details": {}, "evidence_event_ids": [], "source": "t0",
                         "created_at_millis": 1, "correlation_id": "c"}, ev.GateChangeCandidate)


def test_event_types_count_at_least_42():
    assert len(ev.EVENT_TYPES) >= 42
