"""B3.7: run_probe — expected_deny when the gate denies; regression_allow when it allows."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.adversarial.probes import PROBES, KnownBadProbe
from devharness.adversarial.runner import run_all_probes, run_probe
from devharness.events.bus import EventBus
from devharness.gates.base import GateOk
from devharness.gates.registry import GATES, register_gate
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def teardown_function():
    GATES.pop("b37_weak_gate", None)  # don't leak the test gate into the global registry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_expected_deny_emits_run_only():
    conn, bus = _setup()
    result = run_probe(PROBES["scope_out_of_bounds"], conn, bus, now_millis=lambda: 5)
    assert result.outcome == "expected_deny"
    runs = conn.execute("SELECT outcome FROM proj_adversarial WHERE probe_name='scope_out_of_bounds'").fetchall()
    assert runs == [("expected_deny",)]
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='gate_regression_detected'").fetchone()[0] == 0


class _AlwaysAllowGate:
    name = "b37_weak_gate"

    def check(self, context):
        return GateOk()


def test_regression_allow_emits_run_and_regression():
    conn, bus = _setup()
    if "b37_weak_gate" not in GATES:
        register_gate("b37_weak_gate", _AlwaysAllowGate())
    probe = KnownBadProbe(probe_name="b37_weak_probe", target_gate="b37_weak_gate", context_factory=lambda: {"touched_paths": ["x"]})

    result = run_probe(probe, conn, bus, now_millis=lambda: 7)
    assert result.outcome == "regression_allow"
    row = conn.execute("SELECT outcome, regression_reason FROM proj_adversarial WHERE probe_name='b37_weak_probe'").fetchone()
    assert row[0] == "regression_allow" and row[1] is not None
    reg = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='gate_regression_detected'").fetchone()[0])
    assert reg["gate_name"] == "b37_weak_gate" and reg["unexpected_allow_reason"]


def test_run_all_probes_summary():
    conn, bus = _setup()
    summary = run_all_probes(conn, bus, now_millis=lambda: 9)
    assert summary["n_probed"] == len(PROBES)
    assert summary["n_regressions"] == 0  # all built-in gates deny their known-bad
    assert summary["n_expected_deny"] == len(PROBES)
