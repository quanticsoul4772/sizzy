"""B1.2: question_answered exists with the declared fields; EVENT_TYPES is 17."""

import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_question_answered_registered_with_fields():
    assert "question_answered" in ev.EVENT_TYPES
    qa = msgspec.convert(
        {"question_id": "q1", "answer_text": "a", "correlation_id": "c", "answered_at_millis": 5},
        ev.QuestionAnswered,
    )
    assert qa.question_id == "q1"
    assert qa.answer_text == "a"
    assert qa.correlation_id == "c"
    assert qa.answered_at_millis == 5


def test_event_types_count_at_least_17():
    # B1.2 brought the catalog to 17; B1.4 adds tier_floor_violation. The catalog only grows.
    assert len(ev.EVENT_TYPES) >= 17
