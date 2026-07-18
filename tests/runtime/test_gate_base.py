"""B1.3: Gate framework — GateOk/GateDeny shape, envelope required, evaluate emits."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.gates.base import Gate, GateDeny, GateOk, evaluate
from devharness.migrate import migrate


def test_gate_deny_requires_full_envelope():
    GateDeny(reason="r", purpose="p", fix="f")  # ok
    for kwargs in (
        {"reason": "", "purpose": "p", "fix": "f"},
        {"reason": "r", "purpose": "", "fix": "f"},
        {"reason": "r", "purpose": "p", "fix": ""},
    ):
        with pytest.raises(ValueError):
            GateDeny(**kwargs)


class _DenyGate(Gate):
    name = "deny_gate"

    def check(self, context):
        return GateDeny(reason="no", purpose="because", fix="do x")


class _OkGate(Gate):
    name = "ok_gate"

    def check(self, context):
        return GateOk()


def test_evaluate_emits_gate_fired_with_envelope_on_deny():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    result = evaluate(_DenyGate(), {"correlation_id": "corr-1"}, bus)
    assert isinstance(result, GateDeny)
    row = conn.execute("SELECT payload FROM events WHERE event_type='gate_fired'").fetchone()
    payload = json.loads(row[0])
    assert payload["gate"] == "deny_gate"
    assert payload["decision"] == "deny"
    assert payload["reason"] == "no" and payload["purpose"] == "because" and payload["fix"] == "do x"


def test_evaluate_emits_allow():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    result = evaluate(_OkGate(), {"correlation_id": "corr-1"}, bus)
    assert isinstance(result, GateOk)
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='gate_fired'").fetchone()[0])
    assert payload["decision"] == "allow"
