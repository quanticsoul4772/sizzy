"""B2.2: run_verifier emits verifier_outcome with outcome + evidence."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers the falsifiers)
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.verifier.base import Verifier, VerifierFailed, VerifierOk
from devharness.verifier.registry import FALSIFIERS, register_verifier
from devharness.verifier.runner import UnknownVerifier, run_verifier


class _Pass(Verifier):
    name = "_pass"

    async def verify(self, context):
        return VerifierOk(name=self.name, evidence={"ran": True})


class _Fail(Verifier):
    name = "_fail"

    async def verify(self, context):
        return VerifierFailed(name=self.name, reason="boom", evidence={"ran": True})


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn, EventBus(conn)


def _ensure(name, verifier):
    if name not in FALSIFIERS:
        register_verifier(name, verifier)


def test_emits_passed_outcome_with_evidence():
    _ensure("_pass", _Pass())
    conn, bus = _setup()
    result = asyncio.run(run_verifier("_pass", {"task_id": "t1", "correlation_id": "c"}, bus, conn))
    assert isinstance(result, VerifierOk)
    row = conn.execute("SELECT payload FROM events WHERE event_type='verifier_outcome'").fetchone()
    payload = json.loads(row[0])
    assert payload["task_id"] == "t1" and payload["passed"] is True
    assert payload["evidence"] == {"ran": True}


def test_emits_failed_outcome_with_reason():
    _ensure("_fail", _Fail())
    conn, bus = _setup()
    asyncio.run(run_verifier("_fail", {"task_id": "t2", "correlation_id": "c"}, bus, conn))
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='verifier_outcome'").fetchone()[0])
    assert payload["passed"] is False and payload["detail"] == "boom"


def test_unknown_verifier_raises():
    conn, bus = _setup()
    with pytest.raises(UnknownVerifier):
        asyncio.run(run_verifier("nope", {"task_id": "t", "correlation_id": "c"}, bus, conn))
