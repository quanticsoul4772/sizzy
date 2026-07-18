"""B2.5: ReviewerRole — servers, no write tools, fresh context, emits a verdict."""

import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers the falsifiers)
from devharness.call_class import classify
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.roles.fresh_context import FreshContextRequired
from devharness.roles.reviewer import ReviewerRole


class _Result:
    def __init__(self, output):
        self.output = output
        self.cost_usd = 0.0
        self.usage = {}
        self.is_error = False


class _FakeParallax:
    def __init__(self, verdict):
        self._r = _Result(verdict)

    async def verify(self, **p):
        return self._r

    async def check(self, **p):
        return self._r

    async def grounded_verify(self, **p):
        return self._r


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn, EventBus(conn)


def test_allowed_servers_and_no_write_tools():
    conn, bus = _setup()
    reviewer = ReviewerRole.spawn(conn=conn, correlation_id="c", parallax=_FakeParallax({"verified": True}), event_bus=bus, fresh_context=True)
    assert reviewer.allowed_mcp_servers == ["parallax", "devharness-aci"]
    inv = reviewer.tool_inventory
    assert all(classify(t) != "mutation" for t in inv)
    assert "mcp__devharness-aci__run_tests" in inv
    assert not any("write_file" in t or "append_to_file" in t or "run_command" in t for t in inv)


def test_spawn_requires_fresh_context():
    conn, bus = _setup()
    try:
        ReviewerRole.spawn(conn=conn, correlation_id="c", parallax=_FakeParallax({}), event_bus=bus, fresh_context=False)
        raise AssertionError("expected FreshContextRequired")
    except FreshContextRequired:
        pass


def test_emits_certified_when_all_pass(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})())
    conn, bus = _setup()
    reviewer = ReviewerRole.spawn(conn=conn, correlation_id="c", parallax=_FakeParallax({"verified": True}), event_bus=bus, fresh_context=True, now_millis=lambda: 5)
    assert asyncio.run(reviewer.run("t1", "spec-1", "plan-1", "c")) is True
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='reviewer_certified'").fetchone()[0] == 1


def test_emits_rejected_when_a_check_fails(monkeypatch):
    import subprocess
    # the default verifier set is test_suite (rev 0.3.22); a failing test run -> rejection
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("P", (), {"returncode": 1, "stdout": "fail", "stderr": ""})())
    conn, bus = _setup()
    reviewer = ReviewerRole.spawn(conn=conn, correlation_id="c", parallax=_FakeParallax({"verified": False}), event_bus=bus, fresh_context=True)
    assert asyncio.run(reviewer.run("t1", "spec-1", "plan-1", "c")) is False
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='reviewer_rejected'").fetchone()[0] == 1
