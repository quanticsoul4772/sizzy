"""B1.0: the 9 new event types exist; the two discriminator fields are required
and constrained to their value sets."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev

NEW_TYPES = [
    "research_started",
    "question_asked",
    "assumption_flagged",
    "spec_drafted",
    "spec_signed",
    "explore_pass_completed",
    "plan_drafted",
    "director_decision",
    "budget_exceeded",
]


def test_nine_new_event_types_registered():
    for name in NEW_TYPES:
        assert name in ev.EVENT_TYPES, name
    # all carry schema_version
    struct = ev.EVENT_TYPES["research_started"](research_id="r1", topic="t")
    assert struct.schema_version == 1


def test_director_decision_kind_required_and_constrained():
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({"detail": "x"}, ev.DirectorDecision)  # missing discriminator
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({"decision_kind": "nope", "detail": "x"}, ev.DirectorDecision)
    ok = msgspec.convert({"decision_kind": "fork", "detail": "x"}, ev.DirectorDecision)
    assert ok.decision_kind == "fork"


def test_budget_exceeded_kind_required_and_constrained():
    base = {"role": "director", "limit": 1.0, "spent": 2.0}
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert(base, ev.BudgetExceeded)  # missing discriminator
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({**base, "budget_kind": "nope"}, ev.BudgetExceeded)
    ok = msgspec.convert({**base, "budget_kind": "reasoning"}, ev.BudgetExceeded)
    assert ok.budget_kind == "reasoning"
