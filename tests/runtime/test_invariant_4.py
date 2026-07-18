"""B1.3: Invariant 4 — BUILD-class context with no signed spec is denied."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.gates.base import GateDeny, GateOk
from devharness.gates.spec_signed import SpecSignedGate
from devharness.migrate import migrate


def _insert_spec(conn, correlation_id, signed):
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES ('a', 'spec', 1, '{}', ?, 1, ?)",
        (correlation_id, signed),
    )
    conn.commit()


def test_inv4_build_denied_until_signed():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    gate = SpecSignedGate()
    context = {"conn": conn, "correlation_id": "corr-1"}

    # no spec at all -> denied
    assert isinstance(gate.check(context), GateDeny)

    # an unsigned spec -> still denied
    _insert_spec(conn, "corr-1", signed=0)
    assert isinstance(gate.check(context), GateDeny)

    # signed -> allowed (BUILD may proceed)
    conn.execute("UPDATE artifacts SET signed = 1 WHERE correlation_id = 'corr-1'")
    conn.commit()
    assert isinstance(gate.check(context), GateOk)
