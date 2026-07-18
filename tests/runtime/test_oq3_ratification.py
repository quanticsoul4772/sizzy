"""B2.8: OQ3 — new_project_scaffold carries the ratified budget/tier values."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.task_classes.builtin as builtin
from devharness.task_classes.builtin import NEW_PROJECT_SCAFFOLD, register_builtin_task_classes
from devharness.task_classes.registry import TASK_CLASSES, clear_task_classes


def setup_function():
    clear_task_classes()
    register_builtin_task_classes()


def teardown_function():
    clear_task_classes()


def test_ratified_values_registered():
    spec = TASK_CLASSES["new_project_scaffold"]
    assert spec.reasoning_budget_tokens == 40_000
    assert spec.blast_radius_limit == 40
    assert spec.tier_minimum == "T2"
    assert spec.allowed_cost_modes == ["per_token"]


def test_constant_matches_registration():
    assert NEW_PROJECT_SCAFFOLD.reasoning_budget_tokens == 40_000
    assert NEW_PROJECT_SCAFFOLD.blast_radius_limit == 40


def test_ratification_basis_documented():
    # the B2.7 e2e measurement basis is recorded in the module docstring
    doc = builtin.__doc__ or ""
    assert "RATIFICATION" in doc and "B2.7" in doc
    assert "provisional" not in doc.lower().split("ratified")[0] or "no longer provisional" in doc.lower()
