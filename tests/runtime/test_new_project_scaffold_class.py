"""B2.1: new_project_scaffold registered with the declared fields."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_classes.registry import TASK_CLASSES, clear_task_classes


def setup_function():
    clear_task_classes()
    register_builtin_task_classes()


def teardown_function():
    clear_task_classes()


def test_new_project_scaffold_registered():
    spec = TASK_CLASSES["new_project_scaffold"]
    assert spec.tier_minimum == "T2"
    assert spec.dominant_gate_sensitivity == "blast_radius"
    assert spec.allowed_cost_modes == ["per_token"]


def test_provisional_values_present():
    # reasoning_budget_tokens + blast_radius_limit are provisional (ratified B2.8) but must be set
    spec = TASK_CLASSES["new_project_scaffold"]
    assert spec.reasoning_budget_tokens > 0
    assert spec.blast_radius_limit is not None and spec.blast_radius_limit > 0


def test_register_is_idempotent():
    register_builtin_task_classes()  # second call must not raise
    assert "new_project_scaffold" in TASK_CLASSES
