"""B3.7: adversarial events exist with declared fields; EVENT_TYPES is 34."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_adversarial_events_registered():
    assert "adversarial_test_run" in ev.EVENT_TYPES and "gate_regression_detected" in ev.EVENT_TYPES
    r = msgspec.convert({"probe_name": "p", "target_gate": "scope_gate", "outcome": "expected_deny", "gate_check_reason": "x", "correlation_id": "c", "run_at_millis": 1}, ev.AdversarialTestRun)
    assert r.outcome == "expected_deny"
    g = msgspec.convert({"probe_name": "p", "gate_name": "scope_gate", "unexpected_allow_reason": "regressed", "correlation_id": "c", "detected_at_millis": 1}, ev.GateRegressionDetected)
    assert g.gate_name == "scope_gate"


def test_unexpected_allow_reason_non_empty_at_construction():
    ev.GateRegressionDetected(probe_name="p", gate_name="g", unexpected_allow_reason="x", correlation_id="c", detected_at_millis=1)
    with pytest.raises(ValueError):
        ev.GateRegressionDetected(probe_name="p", gate_name="g", unexpected_allow_reason="", correlation_id="c", detected_at_millis=1)


def test_event_types_count_at_least_34():
    assert len(ev.EVENT_TYPES) >= 34
