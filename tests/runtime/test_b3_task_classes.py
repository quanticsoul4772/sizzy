"""B3.1: the four BUILD task classes are registered with their declared TaskClassSpec."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_classes.registry import TASK_CLASSES, TaskClassRegistrationError, clear_task_classes, register_task_class


def setup_function():
    clear_task_classes()
    register_builtin_task_classes()


def teardown_function():
    clear_task_classes()


def test_four_build_classes_registered():
    for name in ("feature", "bugfix", "refactor", "dependency_bump"):
        assert name in TASK_CLASSES
    assert "new_project_scaffold" in TASK_CLASSES  # B2.1 still present


def test_declared_specs():
    f = TASK_CLASSES["feature"]
    # blast_radius_limit=21: RATIFIED rev 0.3.66 from realized telemetry (60 tasks, max 14, ceil(14*1.5))
    assert f.tier_minimum == "T2" and f.reasoning_budget_tokens == 50_000 and f.blast_radius_limit == 21
    assert f.allowed_cost_modes == ["per_token"] and "scope" in f.dominant_gate_sensitivity

    b = TASK_CLASSES["bugfix"]
    assert b.blast_radius_limit == 10 and "verifier_attached" in b.dominant_gate_sensitivity

    r = TASK_CLASSES["refactor"]
    assert r.blast_radius_limit == 80 and "blast_radius" in r.dominant_gate_sensitivity

    d = TASK_CLASSES["dependency_bump"]
    assert d.blast_radius_limit == 200 and d.dominant_gate_sensitivity == "blast_radius+verifier_attached"


def test_all_write_classes_force_per_token():
    for name in ("feature", "bugfix", "refactor", "dependency_bump"):
        assert TASK_CLASSES[name].allowed_cost_modes == ["per_token"]


def test_register_task_class_single_write_enforced():
    with pytest.raises(TaskClassRegistrationError):
        register_task_class(TASK_CLASSES["feature"])  # re-register the same name -> raise
