"""B1.3: SpecSignedGate pass/deny + documented envelope + gate_fired."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.gates.base import GateDeny, GateOk, evaluate
from devharness.gates.spec_signed import SpecSignedGate
from devharness.migrate import migrate


def _insert_spec(conn, correlation_id, signed):
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, '{}', ?, ?, ?)",
        (f"a-{correlation_id}-{signed}", correlation_id, 1, signed),
    )
    conn.commit()


def test_passes_when_signed_spec_exists():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    _insert_spec(conn, "corr-1", signed=1)
    assert isinstance(SpecSignedGate().check({"conn": conn, "correlation_id": "corr-1"}), GateOk)


def test_denies_when_no_spec_with_documented_envelope():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    deny = SpecSignedGate().check({"conn": conn, "correlation_id": "corr-1"})
    assert isinstance(deny, GateDeny)
    assert deny.reason == "No signed spec artifact for correlation_id corr-1"
    assert deny.purpose == "BUILD requires an operator-signed spec (Invariant 4, Commitment 12)"
    assert deny.fix == "Draft a spec via the research role and run `devharness sign <spec_id>` to sign it"


def test_denies_when_unsigned():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    _insert_spec(conn, "corr-1", signed=0)
    assert isinstance(SpecSignedGate().check({"conn": conn, "correlation_id": "corr-1"}), GateDeny)


def test_evaluate_emits_gate_fired():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    evaluate(SpecSignedGate(), {"conn": conn, "correlation_id": "corr-1"}, bus)
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='gate_fired'").fetchone()[0])
    assert payload["gate"] == "spec_signed_gate"
    assert payload["decision"] == "deny"
