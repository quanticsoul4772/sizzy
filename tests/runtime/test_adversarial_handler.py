"""B3.7: adversarial handlers update proj_adversarial; rebuild parity across runs + regressions."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, registry, EventBus(conn, registry)


def _emit(bus):
    bus.emit_sync("adversarial_test_run", {"probe_name": "scope_oob", "target_gate": "scope_gate", "outcome": "expected_deny", "gate_check_reason": "denied", "correlation_id": "a", "run_at_millis": 10}, correlation_id="a")
    bus.emit_sync("adversarial_test_run", {"probe_name": "weak", "target_gate": "weak_gate", "outcome": "regression_allow", "gate_check_reason": "allowed", "correlation_id": "a", "run_at_millis": 11}, correlation_id="a")
    bus.emit_sync("gate_regression_detected", {"probe_name": "weak", "gate_name": "weak_gate", "unexpected_allow_reason": "gate returned GateOk", "correlation_id": "a", "detected_at_millis": 11}, correlation_id="a")


def test_handlers_record_runs_and_regression():
    conn, _registry, bus = _setup()
    _emit(bus)
    expected = conn.execute("SELECT outcome, regression_reason FROM proj_adversarial WHERE probe_name='scope_oob'").fetchone()
    assert expected == ("expected_deny", None)
    regression = conn.execute("SELECT outcome, regression_reason FROM proj_adversarial WHERE probe_name='weak'").fetchone()
    assert regression == ("regression_allow", "gate returned GateOk")


def test_rebuild_parity():
    conn, registry, bus = _setup()
    _emit(bus)
    assert check_projection_rebuild_parity(conn, registry) is True
