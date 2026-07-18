"""B5.4: CandidateReviewed event — declared fields + validations; EVENT_TYPES 47."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_candidate_reviewed_registered():
    assert "candidate_reviewed" in ev.EVENT_TYPES
    r = ev.CandidateReviewed(candidate_row_id=1, candidate_kind="antibody_candidate", review_state="approved",
                             reviewed_by="op", review_reason="", reviewed_at_millis=5, correlation_id="c")
    assert r.review_state == "approved" and r.review_reason == ""


def test_review_reason_required_when_rejected():
    ev.CandidateReviewed(candidate_row_id=1, candidate_kind="antibody_candidate", review_state="rejected",
                         reviewed_by="op", review_reason="bad", reviewed_at_millis=1, correlation_id="c")
    with pytest.raises(ValueError):
        ev.CandidateReviewed(candidate_row_id=1, candidate_kind="antibody_candidate", review_state="rejected",
                             reviewed_by="op", review_reason="", reviewed_at_millis=1, correlation_id="c")


def test_literals_validated():
    base = {"candidate_row_id": 1, "candidate_kind": "antibody_candidate", "review_state": "approved",
            "reviewed_by": "op", "review_reason": "", "reviewed_at_millis": 1, "correlation_id": "c"}
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({**base, "review_state": "maybe"}, ev.CandidateReviewed)
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({**base, "candidate_kind": "bogus"}, ev.CandidateReviewed)


def test_event_types_count_at_least_47():
    assert len(ev.EVENT_TYPES) >= 47
