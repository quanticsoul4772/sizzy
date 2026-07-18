"""B1.4: task class registry — sole writer, single-write, ships empty."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.task_classes.base import TaskClassSpec
from devharness.task_classes.registry import (
    TASK_CLASSES,
    TaskClassRegistrationError,
    clear_task_classes,
    register_task_class,
)


def setup_function():
    clear_task_classes()


def teardown_function():
    clear_task_classes()


def test_ships_empty():
    assert TASK_CLASSES == {}


def test_register_then_present():
    spec = TaskClassSpec(name="feature", reasoning_budget_tokens=50_000, tier_minimum="T2", dominant_gate_sensitivity="reviewer")
    register_task_class(spec)
    assert TASK_CLASSES["feature"] is spec


def test_single_write_enforcement():
    spec = TaskClassSpec(name="feature", reasoning_budget_tokens=50_000, tier_minimum="T2", dominant_gate_sensitivity="reviewer")
    register_task_class(spec)
    with pytest.raises(TaskClassRegistrationError):
        register_task_class(spec)


def _spec(name, tier):
    return TaskClassSpec(name=name, reasoning_budget_tokens=1, tier_minimum=tier,
                         dominant_gate_sensitivity="x", blast_radius_limit=1,
                         allowed_cost_modes=["per_token"])


def test_batch_writer_tier_highest_wins():
    # rev 0.3.85: a batch of tasks sharing one developer model takes the HIGHEST class tier, so a
    # mixed batch never downgrades a frontier-tier (T2) task; single low-tier batches run cheaper.
    from devharness.task_classes.registry import batch_writer_tier

    register_task_class(_spec("bump", "T1"))
    register_task_class(_spec("feat", "T2"))
    assert batch_writer_tier(["bump"]) == "T1"          # single low-tier -> cheaper
    assert batch_writer_tier(["bump", "bump"]) == "T1"
    assert batch_writer_tier(["bump", "feat"]) == "T2"  # mixed -> highest wins (no T2 downgrade)
    assert batch_writer_tier(["unknown"]) == "T2"       # unknown class -> frontier
    assert batch_writer_tier([]) == "T2"                # empty -> frontier
