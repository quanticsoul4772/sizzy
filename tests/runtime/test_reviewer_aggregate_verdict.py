"""B2.5: reviewer aggregates the 4 falsifiers to one verdict."""

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.roles.reviewer import CLAIM_VERIFIERS, ReviewerRole


class _Result:
    def __init__(self, output):
        self.output = output
        self.cost_usd = 0.0
        self.usage = {}
        self.is_error = False


class _FakeParallax:
    """verify/check/grounded_verify each return their own configured verdict."""

    def __init__(self, verify=True, check=True, grounded=True):
        self._verify = _Result({"verified": verify})
        self._check = _Result({"consistent": check})
        self._grounded = _Result({"supported": grounded})

    async def verify(self, **p):
        return self._verify

    async def check(self, **p):
        return self._check

    async def grounded_verify(self, **p):
        return self._grounded


def _reviewer(parallax, tests_pass=True):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    # this suite exercises the 4-falsifier aggregation, so pass the explicit claim-bearing set
    reviewer = ReviewerRole.spawn(conn=conn, correlation_id="c", parallax=parallax, event_bus=bus,
                                  fresh_context=True, verifiers=CLAIM_VERIFIERS)
    return conn, reviewer


def _mock_tests(monkeypatch, returncode):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("P", (), {"returncode": returncode, "stdout": "", "stderr": ""})())


def test_all_pass_certifies(monkeypatch):
    _mock_tests(monkeypatch, 0)
    conn, reviewer = _reviewer(_FakeParallax(True, True, True))
    assert asyncio.run(reviewer.run("t1", "s", "p", "c")) is True
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='reviewer_certified'").fetchone()[0] == 1


def test_parallax_check_fail_rejects_with_reason(monkeypatch):
    _mock_tests(monkeypatch, 0)
    conn, reviewer = _reviewer(_FakeParallax(verify=True, check=False, grounded=True))
    assert asyncio.run(reviewer.run("t1", "s", "p", "c")) is False
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='reviewer_rejected'").fetchone()[0])
    assert "parallax_check" in payload["reason"]
    assert "parallax_check" in payload["evidence"]


def test_test_suite_fail_rejects(monkeypatch):
    _mock_tests(monkeypatch, 1)  # tests fail
    conn, reviewer = _reviewer(_FakeParallax(True, True, True))
    assert asyncio.run(reviewer.run("t1", "s", "p", "c")) is False
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='reviewer_rejected'").fetchone()[0])
    assert "test_suite" in payload["reason"]


def test_default_verifier_set_is_test_suite_only_no_claim_misfire(monkeypatch):
    # rev 0.3.22 (#2c): the DEFAULT cert is test_suite only. A scaffold with no claim/sources
    # certifies on passing tests, without the claim-based parallax verifiers misfiring (here all
    # three parallax verdicts are False — they must not be consulted by the default set).
    _mock_tests(monkeypatch, 0)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    reviewer = ReviewerRole.spawn(  # no verifiers= -> the default set
        conn=conn, correlation_id="c", event_bus=bus, fresh_context=True,
        parallax=_FakeParallax(verify=False, check=False, grounded=False),
    )
    assert asyncio.run(reviewer.run("t1", "s", "p", "c")) is True
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='reviewer_certified'").fetchone()[0] == 1
