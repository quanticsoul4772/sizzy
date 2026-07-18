"""B3.6: maintenance class permits flat-cost; the cost-mode gate denies flat for write classes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cost_router import CostModeGate, allowed_cost_modes_for, requires_per_token
from devharness.gates.base import GateDeny, GateOk
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_classes.registry import TASK_CLASSES, clear_task_classes


def setup_function():
    clear_task_classes()
    register_builtin_task_classes()


def teardown_function():
    clear_task_classes()


def test_maintenance_registered_with_flat():
    spec = TASK_CLASSES["maintenance"]
    assert spec.tier_minimum == "T0" and spec.blast_radius_limit == 0
    assert spec.allowed_cost_modes == ["per_token", "flat"]


def test_gate_accepts_flat_for_maintenance():
    gate = CostModeGate()
    assert isinstance(gate.check({"task_class": "maintenance", "cost_mode": "flat"}), GateOk)
    assert isinstance(gate.check({"task_class": "maintenance", "cost_mode": "per_token"}), GateOk)


def test_gate_denies_flat_for_write_classes():
    gate = CostModeGate()
    for write_class in ("new_project_scaffold", "feature", "bugfix", "refactor", "dependency_bump"):
        assert isinstance(gate.check({"task_class": write_class, "cost_mode": "flat"}), GateDeny)
        assert isinstance(gate.check({"task_class": write_class, "cost_mode": "per_token"}), GateOk)
        assert requires_per_token(write_class) is True
    assert requires_per_token("maintenance") is False
    assert "flat" in allowed_cost_modes_for("maintenance")
