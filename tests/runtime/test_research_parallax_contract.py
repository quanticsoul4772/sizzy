"""research.py's interview loop calls parallax with the REAL tool schemas (elicit: task/context,
diverge: problem/context) — not the idea=/asked=/question=/answer= shapes it used before. Also proves
the dead research() web-search call (whose result was never consumed) is gone, and that elicit's context
actually threads prior rounds' Q/A across the loop, not just that the call compiles.
"""

import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.roles.research import ResearchRole


class _Out:
    def __init__(self, output, is_error=False):
        self.output = output
        self.is_error = is_error


class _RecordingParallax:
    """No `complete` method -> _synthesize_body returns None -> the templated fallback body is used,
    so these tests don't need a valid JSON spec body."""

    def __init__(self, elicit_outputs):
        self.elicit_calls = []
        self.diverge_calls = []
        self.research_calls = []
        self._elicit_outputs = iter(elicit_outputs)

    async def elicit(self, *, task, context=None):
        self.elicit_calls.append({"task": task, "context": context})
        out = next(self._elicit_outputs)
        return out if isinstance(out, _Out) else _Out(out)

    async def diverge(self, *, problem, context=None):
        self.diverge_calls.append({"problem": problem, "context": context})
        return _Out("alt framing")

    async def research(self, **kwargs):  # must never be invoked
        self.research_calls.append(kwargs)
        return _Out("noted")


def _role(conn, fake, **kwargs):
    return ResearchRole.spawn(
        conn=conn, correlation_id="c1", parallax=fake, event_bus=EventBus(conn),
        answer_fn=lambda qid, qt: f"answer for {qid}", now_millis=lambda: 7, **kwargs,
    )


def _payload(question):
    # rev 0.4.11: elicit results are payload-shaped per the server contract — bare prose is now
    # (correctly) an errored round, so the contract fixtures carry the real shape.
    import json
    return json.dumps({"assumed_objective": "build X", "signal_level": "high",
                       "divergence_points": [{"question": question, "signal": "s"}]})


def test_elicit_uses_task_and_context_with_progressive_round_history(tmp_path):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    fake = _RecordingParallax([_payload("What's the scope?"), _payload("What's the priority?")])
    role = _role(conn, fake, max_questions=2)
    asyncio.run(role.run("build a thing", "c1"))

    assert fake.elicit_calls[0] == {"task": "build a thing", "context": None}
    assert fake.elicit_calls[1]["context"] is not None
    assert "What's the scope?" in fake.elicit_calls[1]["context"]
    assert "answer for" in fake.elicit_calls[1]["context"]


def test_no_research_tool_invoked_during_interview(tmp_path):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    fake = _RecordingParallax([_payload("What's the scope?"), _payload("What's the priority?")])
    role = _role(conn, fake, max_questions=2)
    asyncio.run(role.run("build a thing", "c1"))

    assert fake.research_calls == []


def test_diverge_called_with_problem_when_interview_errors_hard(tmp_path):
    # the diverge-with-problem contract, exercised via the 0.3.76 is_error break (the diverge
    # guard then screens ITS result separately — here it returns clean text, which is used).
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    fake = _RecordingParallax([_Out("MCP error -32603: boom", is_error=True)])
    role = _role(conn, fake, max_questions=2)
    asyncio.run(role.run("some idea", "c1"))

    assert fake.diverge_calls == [{"problem": "some idea", "context": None}]
    assert fake.elicit_calls == [{"task": "some idea", "context": None}]


def test_empty_elicit_is_retried_once_then_diverge_is_skipped(tmp_path):
    # rev 0.4.11: an empty result is the same stochastic failure class as shapeless prose — one
    # retry, then a STRUCTURAL break, and the diverge fallback (same failing client) is skipped
    # in favor of the neutral placeholder (the plan-review blocker).
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    fake = _RecordingParallax(["", ""])
    role = _role(conn, fake, max_questions=2)
    asyncio.run(role.run("some idea", "c1"))

    assert len(fake.elicit_calls) == 2  # the one structural retry
    assert fake.diverge_calls == []     # never consulted after a structural break
    notes = [r[0] for r in conn.execute(
        "SELECT json_extract(payload,'$.text') FROM events WHERE event_type='assumption_flagged'")]
    assert notes == ["needs operator review"]
