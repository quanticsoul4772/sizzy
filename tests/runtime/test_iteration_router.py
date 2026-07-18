"""B1.4: iteration_rate_stakes_router.select_path."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.roles.iteration_router import (
    DEFAULT_REASONING_BUDGET_TOKENS,
    DEFAULT_TIER_MINIMUM,
    select_path,
)
from devharness.task_classes.base import TaskClassSpec
from devharness.task_classes.registry import clear_task_classes, register_task_class


def setup_function():
    clear_task_classes()


def teardown_function():
    clear_task_classes()


def test_unknown_class_falls_back_to_defaults():
    budget, tier, depth = select_path("not-registered", 0.5)
    assert budget == DEFAULT_REASONING_BUDGET_TOKENS
    assert tier == DEFAULT_TIER_MINIMUM
    assert depth == 1


def test_known_class_respects_tier_minimum_and_returns_tuple():
    register_task_class(
        TaskClassSpec(name="refactor", reasoning_budget_tokens=10_000, tier_minimum="T3", dominant_gate_sensitivity="reviewer")
    )
    budget, tier, depth = select_path("refactor", 0.0)
    assert tier == "T3"  # class floor preserved
    assert budget == 10_000  # stakes 0 -> base budget
    assert depth == 1


def test_higher_stakes_deepens_path_within_tier():
    register_task_class(
        TaskClassSpec(name="feature", reasoning_budget_tokens=10_000, tier_minimum="T2", dominant_gate_sensitivity="reviewer")
    )
    low = select_path("feature", 0.0)
    high = select_path("feature", 1.0)
    assert high[2] > low[2]  # deeper path at higher stakes
    assert high[0] > low[0]  # bigger budget at higher stakes
    assert high[1] == low[1] == "T2"  # tier floor unchanged
