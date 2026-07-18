"""Operator console research action: start a research session and submit interview answers.

The console replaces the LLM in the operator seat — it issues the same operations as the
``run_research`` driver (research_started / question_asked / question_answered), records every
event through ``EventBus.emit_sync``, and attributes each to the operator.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console import ConsoleResearch, UnknownQuestion
from devharness.console.app import ConsoleApp


def _app():
    """A console connected to a fresh in-memory event store (migrated)."""
    return ConsoleApp(db_path=":memory:").connect()


def _events(conn, event_type):
    return [
        json.loads(payload)
        for (payload,) in conn.execute(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY seq", (event_type,)
        )
    ]


def test_start_research_emits_operator_attributed_event():
    app = _app()
    research_id = app.research(operator="ada").start_research("a stdlib CSV query CLI", correlation_id="proj-1")

    assert research_id == "proj-1"
    started = _events(app.conn, "research_started")
    assert len(started) == 1
    assert started[0]["research_id"] == "proj-1"
    assert started[0]["topic"] == "a stdlib CSV query CLI"
    # recorded as an operator-attributed event
    assert started[0]["operator"] == "ada"


def test_start_research_mints_id_when_unspecified():
    app = _app()
    research_id = app.research(operator="ada").start_research("some idea")
    assert isinstance(research_id, str) and research_id
    assert _events(app.conn, "research_started")[0]["research_id"] == research_id


def test_topic_is_bounded_like_run_research():
    app = _app()
    long_topic = "x" * 500
    app.research(operator="ada").start_research(long_topic, correlation_id="proj-1")
    assert _events(app.conn, "research_started")[0]["topic"] == "x" * 120


def test_ask_question_uses_run_research_id_convention():
    app = _app()
    r = app.research(operator="ada")
    r.start_research("idea", correlation_id="proj-1")
    q0 = r.ask_question("proj-1", "what is the scope?")
    q1 = r.ask_question("proj-1", "any non-goals?")

    assert q0 == "proj-1-q0"
    assert q1 == "proj-1-q1"
    asked = _events(app.conn, "question_asked")
    assert [q["question_id"] for q in asked] == ["proj-1-q0", "proj-1-q1"]
    assert all(q["operator"] == "ada" for q in asked)


def test_submit_answer_records_operator_attributed_question_answered():
    app = _app()
    r = app.research(operator="ada")
    r.start_research("idea", correlation_id="proj-1")
    qid = r.ask_question("proj-1", "what is the scope?")

    returned = r.submit_answer(qid, "a stdlib-only CSV query CLI")
    assert returned == qid

    answered = _events(app.conn, "question_answered")
    assert len(answered) == 1
    assert answered[0]["question_id"] == "proj-1-q0"
    assert answered[0]["answer_text"] == "a stdlib-only CSV query CLI"
    assert answered[0]["correlation_id"] == "proj-1"
    assert answered[0]["operator"] == "ada"


def test_answer_flows_into_the_projection():
    app = _app()
    r = app.research(operator="ada")
    r.start_research("idea", correlation_id="proj-1")
    qid = r.ask_question("proj-1", "what is the scope?")
    r.submit_answer(qid, "stdlib-only")

    row = app.conn.execute(
        "SELECT answered, answer_text FROM proj_questions WHERE question_id = ?", (qid,)
    ).fetchone()
    assert row == (1, "stdlib-only")


def test_submit_answer_refuses_unknown_question():
    r = _app().research(operator="ada")
    with pytest.raises(UnknownQuestion):
        r.submit_answer("proj-1-q0", "answer with no question")


def test_per_call_operator_overrides_instance_default():
    app = _app()
    app.research(operator="ada").start_research("idea", correlation_id="proj-1", operator="grace")
    assert _events(app.conn, "research_started")[0]["operator"] == "grace"


def test_operator_defaults_to_resolved_identity():
    app = _app()
    app.research().start_research("idea", correlation_id="proj-1")
    operator = _events(app.conn, "research_started")[0]["operator"]
    assert isinstance(operator, str) and operator  # DEVHARNESS_OPERATOR / git user / "unknown"


def test_actions_write_only_through_emit_sync():
    """ConsoleResearch holds no raw cursor write path — it issues events via the EventBus only."""
    app = _app()
    r = app.research(operator="ada")
    # the writer it acts through is the console's emit-only EventBus
    from devharness.events.bus import EventBus

    assert isinstance(r._writer, EventBus)

    before = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    r.start_research("idea", correlation_id="proj-1")
    after = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert after == before + 1  # exactly one appended event, via emit_sync


def test_full_round_trip_matches_run_research_operations():
    """Start → ask → answer issues exactly the run_research event sequence, operator-attributed."""
    app = _app()
    r = app.research(operator="ada")
    r.start_research("a stdlib CSV query CLI", correlation_id="proj-1")
    qid = r.ask_question("proj-1", "what is the scope?")
    r.submit_answer(qid, "stdlib-only")

    seq = [
        row[0]
        for row in app.conn.execute("SELECT event_type FROM events ORDER BY seq")
    ]
    assert seq == ["research_started", "question_asked", "question_answered"]
