"""B1.2: `devharness answer` emits question_answered and refuses unknown ids."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cli.answer import UnknownQuestion, answer_question
from devharness.events.bus import EventBus
from devharness.migrate import migrate


def _seed_question(bus, question_id, correlation_id):
    bus.emit_sync(
        "question_asked",
        {"research_id": correlation_id, "question_id": question_id, "question_text": "what scope?"},
        correlation_id=correlation_id,
    )


def test_answer_emits_question_answered():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    _seed_question(bus, "q1", "corr-1")

    answer_question(conn, bus, "q1", "the whole repo", now_millis=lambda: 123)

    rows = conn.execute(
        "SELECT correlation_id, payload FROM events WHERE event_type = 'question_answered'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "corr-1"  # answer carries the question's correlation_id
    payload = json.loads(rows[0][1])
    assert payload["question_id"] == "q1"
    assert payload["answer_text"] == "the whole repo"
    assert payload["answered_at_millis"] == 123


def test_refuses_unknown_question_id():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    with pytest.raises(UnknownQuestion):
        answer_question(conn, bus, "nope", "x")
