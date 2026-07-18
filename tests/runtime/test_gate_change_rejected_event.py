"""B5.3: GateChangeRejected event — declared fields + validations; EVENT_TYPES 46."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_gate_change_rejected_registered():
    assert "gate_change_rejected" in ev.EVENT_TYPES
    r = ev.GateChangeRejected(candidate_row_id=1, target_gate="secret_guard", change_kind="loosen",
                              rejection_reason="core_gate_weakening", auto_rejected=True, rejected_at_millis=5, correlation_id="c")
    assert r.auto_rejected is True and r.rejection_reason == "core_gate_weakening"


def test_rejection_reason_required():
    with pytest.raises(ValueError):
        ev.GateChangeRejected(candidate_row_id=1, target_gate="g", change_kind="loosen",
                              rejection_reason="", auto_rejected=True, rejected_at_millis=1, correlation_id="c")


def test_event_types_count_at_least_46():
    assert len(ev.EVENT_TYPES) >= 46
