"""B2.5: ReviewerCertified/ReviewerRejected events; EVENT_TYPES is 26."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_reviewer_events_registered():
    assert "reviewer_certified" in ev.EVENT_TYPES and "reviewer_rejected" in ev.EVENT_TYPES
    cert = msgspec.convert(
        {"task_id": "t", "reviewer_session_id": "s", "evidence": {"k": 1}, "correlation_id": "c", "certified_at_millis": 1},
        ev.ReviewerCertified,
    )
    assert cert.reviewer_session_id == "s" and cert.evidence == {"k": 1}
    rej = msgspec.convert(
        {"task_id": "t", "reviewer_session_id": "s", "reason": "tests failed", "evidence": {}, "correlation_id": "c", "rejected_at_millis": 2},
        ev.ReviewerRejected,
    )
    assert rej.reason == "tests failed"


def test_reviewer_rejected_reason_non_empty_at_construction():
    ev.ReviewerRejected(task_id="t", reviewer_session_id="s", reason="x", evidence={}, correlation_id="c", rejected_at_millis=1)
    with pytest.raises(ValueError):
        ev.ReviewerRejected(task_id="t", reviewer_session_id="s", reason="", evidence={}, correlation_id="c", rejected_at_millis=1)


def test_event_types_count_at_least_26():
    assert len(ev.EVENT_TYPES) >= 26
