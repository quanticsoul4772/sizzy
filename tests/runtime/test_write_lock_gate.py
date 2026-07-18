"""B2.0: WriteLockGate pass/deny + documented envelope + gate_fired."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.gates.base import GateDeny, GateOk, evaluate
from devharness.gates.write_lock import WriteLockGate
from devharness.migrate import migrate


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def _hold(conn, holder="developer", correlation_id="c1"):
    conn.execute(
        "INSERT INTO proj_lock (lock_token, holder_role, correlation_id, acquired_at_millis) VALUES ('t', ?, ?, 1)",
        (holder, correlation_id),
    )
    conn.commit()


def test_ok_when_no_holder():
    conn = _db()
    assert isinstance(WriteLockGate().check({"conn": conn, "holder_role": "developer"}), GateOk)


def test_ok_when_same_holder():
    conn = _db()
    _hold(conn, "developer")
    assert isinstance(WriteLockGate().check({"conn": conn, "holder_role": "developer"}), GateOk)


def test_deny_when_other_holder_with_documented_envelope():
    conn = _db()
    _hold(conn, "developer", "c1")
    deny = WriteLockGate().check({"conn": conn, "holder_role": "reviewer"})
    assert isinstance(deny, GateDeny)
    assert deny.reason == "Write lock held by developer for correlation_id c1"
    assert deny.purpose == "Single-writer invariant: only one role edits code at a time (Invariant 1, Commitment 11)"
    assert deny.fix == "Wait for the holder to release the lock, or release it via the runtime lock API"


def test_evaluate_emits_gate_fired():
    conn = _db()
    _hold(conn, "developer", "c1")
    bus = EventBus(conn)
    evaluate(WriteLockGate(), {"conn": conn, "correlation_id": "c1", "holder_role": "reviewer"}, bus)
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='gate_fired'").fetchone()[0])
    assert payload["gate"] == "write_lock_gate"
    assert payload["decision"] == "deny"
