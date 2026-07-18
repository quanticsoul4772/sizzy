"""B4.1: IntakeDecision event — declared fields + rejection_reason validation; EVENT_TYPES 36."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_intake_decision_registered():
    assert "intake_decision" in ev.EVENT_TYPES
    d = msgspec.convert(
        {"intake_correlation_id": "i1", "decision": "accepted", "rejection_reason": "",
         "detected_patterns": [], "decision_at_millis": 5, "correlation_id": "c"},
        ev.IntakeDecision,
    )
    assert d.decision == "accepted" and d.intake_correlation_id == "i1"


def test_rejection_reason_required_when_rejected():
    ev.IntakeDecision(intake_correlation_id="i1", decision="rejected", rejection_reason="license_disallowed",
                      detected_patterns=[], decision_at_millis=1, correlation_id="c")
    with pytest.raises(ValueError):
        ev.IntakeDecision(intake_correlation_id="i1", decision="rejected", rejection_reason="",
                          detected_patterns=[], decision_at_millis=1, correlation_id="c")


def test_accepted_allows_empty_reason():
    d = ev.IntakeDecision(intake_correlation_id="i1", decision="accepted", rejection_reason="",
                          detected_patterns=[], decision_at_millis=1, correlation_id="c")
    assert d.rejection_reason == ""


def test_event_types_count_at_least_36():
    assert len(ev.EVENT_TYPES) >= 36
