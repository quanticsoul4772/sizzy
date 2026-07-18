"""B1.2: at most one unresolved question_asked at a time; the next emits only
after the matching question_answered lands."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.mcp.parallax import ParallaxClient
from devharness.roles.research import ResearchRole


class _R:
    def __init__(self, text):
        self.total_cost_usd = 0.0
        self.result = text
        self.usage = {}
        self.is_error = False


def _query(text):
    async def query(*, prompt, options):
        yield _R(text)

    return query


def _query_seq(texts):
    state = {"i": 0}

    async def query(*, prompt, options):
        i = min(state["i"], len(texts) - 1)
        state["i"] += 1
        yield _R(texts[i])

    return query


def _div(question, signal):
    return json.dumps({"assumed_objective": "build X", "signal_level": "high",
                       "divergence_points": [{"question": question, "signal": signal}]})


def test_one_unresolved_question_at_a_time():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)

    def answer(question_id, question_text):
        # operator answers (via the event log) before the next question is asked
        bus.emit_sync(
            "question_answered",
            {"question_id": question_id, "answer_text": "ok", "correlation_id": "corr-1", "answered_at_millis": 1},
            correlation_id="corr-1",
        )
        return "ok"

    # distinct questions per round (a fixed identical payload now correctly trips the rev-0.3.86
    # re-ask backstop; this test's concern is the one-unresolved-at-a-time ordering, not repetition).
    payloads = [_div(f"alpha{i} bravo{i}", f"charlie{i} delta{i}") for i in range(3)]
    role = ResearchRole.spawn(
        conn=conn,
        correlation_id="corr-1",
        parallax=ParallaxClient(query_fn=_query_seq(payloads)),
        event_bus=bus,
        answer_fn=answer,
        max_questions=3,
        now_millis=lambda: 1,
    )
    asyncio.run(role.run("idea", "corr-1"))

    unresolved = set()
    for event_type, payload in conn.execute("SELECT event_type, payload FROM events ORDER BY seq"):
        record = json.loads(payload)
        if event_type == "question_asked":
            assert len(unresolved) == 0, "a question was asked while another was unresolved"
            unresolved.add(record["question_id"])
        elif event_type == "question_answered":
            unresolved.discard(record["question_id"])
    assert len(unresolved) == 0
    # three questions were asked and each answered
    asked = conn.execute("SELECT count(*) FROM events WHERE event_type='question_asked'").fetchone()[0]
    answered = conn.execute("SELECT count(*) FROM events WHERE event_type='question_answered'").fetchone()[0]
    assert asked == 3 and answered == 3
