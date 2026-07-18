"""B5.2: AntibodyAdded + AntibodyRevoked + CandidateRejected events; EVENT_TYPES 45."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_antibody_added_requires_pattern_text():
    ev.AntibodyAdded(antibody_row_id=1, pattern_text="x", source_candidate_id="c", added_by="op", added_at_millis=1, correlation_id="c")
    with pytest.raises(ValueError):
        ev.AntibodyAdded(antibody_row_id=1, pattern_text="", source_candidate_id="c", added_by="op", added_at_millis=1, correlation_id="c")


def test_antibody_revoked_requires_reason():
    ev.AntibodyRevoked(antibody_row_id=1, reason="dupe", revoked_by="op", revoked_at_millis=1, correlation_id="c")
    with pytest.raises(ValueError):
        ev.AntibodyRevoked(antibody_row_id=1, reason="", revoked_by="op", revoked_at_millis=1, correlation_id="c")


def test_candidate_rejected_kind_literal_validated():
    ev.CandidateRejected(candidate_row_id=1, candidate_kind="antibody_candidate", rejected_by="op", reason="r", rejected_at_millis=1, correlation_id="c")
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({"candidate_row_id": 1, "candidate_kind": "bogus", "rejected_by": "op", "reason": "r", "rejected_at_millis": 1, "correlation_id": "c"}, ev.CandidateRejected)


def test_all_registered():
    for name in ("antibody_added", "antibody_revoked", "candidate_rejected"):
        assert name in ev.EVENT_TYPES


def test_event_types_count_at_least_45():
    assert len(ev.EVENT_TYPES) >= 45
