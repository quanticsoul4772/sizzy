"""B2.1: BlastRadiusGate allows under limit, denies over limit."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.gates.base import GateDeny, GateOk
from devharness.gates.blast_radius import BlastRadiusGate
from devharness.task_classes.base import TaskClassSpec
from devharness.task_classes.registry import clear_task_classes, register_task_class


def setup_function():
    clear_task_classes()
    register_task_class(
        TaskClassSpec(name="scaffold", reasoning_budget_tokens=1, tier_minimum="T2", dominant_gate_sensitivity="blast_radius", blast_radius_limit=3)
    )


def teardown_function():
    clear_task_classes()


def test_allows_under_limit():
    ctx = {"task_class": "scaffold", "touched_paths": ["a", "b", "c"]}
    assert isinstance(BlastRadiusGate().check(ctx), GateOk)


def test_denies_over_limit_with_envelope():
    ctx = {"task_class": "scaffold", "touched_paths": ["a", "b", "c", "d"]}
    deny = BlastRadiusGate().check(ctx)
    assert isinstance(deny, GateDeny)
    assert deny.reason == "Task touches 4 files, exceeds blast_radius_limit 3 for task_class scaffold"
    assert deny.purpose == "Blast-radius invariant: tasks must respect their declared reach"
    assert deny.fix == "Split into multiple tasks, or raise blast_radius_limit on the task class"


def test_no_limit_passes():
    # an unknown class with no limit and no context limit passes
    assert isinstance(BlastRadiusGate().check({"task_class": "unknown", "touched_paths": ["a", "b", "c", "d", "e"]}), GateOk)


def test_distinct_files_counted():
    ctx = {"task_class": "scaffold", "touched_paths": ["a", "a", "b"]}  # 2 distinct, under 3
    assert isinstance(BlastRadiusGate().check(ctx), GateOk)
