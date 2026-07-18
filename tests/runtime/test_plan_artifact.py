"""B1.4: PlanArtifact + PlannedTask schema and "plan" handoff registration."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts import registry
from devharness.artifacts.plan import PlanArtifact, PlannedTask


def _task(**overrides):
    base = dict(
        task_id="t0",
        task_class="feature",
        description="do the thing",
        scope_boundary=["src/**"],
        dependencies=[],
        correlation_id="corr-1",
    )
    base.update(overrides)
    return PlannedTask(**base)


def test_plan_registered_in_handoff():
    assert registry.HANDOFF_ARTIFACTS.get("plan") is PlanArtifact


def test_plan_validates_required_fields():
    plan = PlanArtifact(
        plan_id="p1", spec_artifact_id="s1", tasks=[_task()], correlation_id="corr-1", created_at_millis=1
    )
    assert plan.tasks[0].task_class == "feature"


def test_tasks_list_may_be_empty():
    plan = PlanArtifact(plan_id="p1", spec_artifact_id="s1", tasks=[], correlation_id="corr-1", created_at_millis=1)
    assert plan.tasks == []


def test_planned_task_requires_task_class():
    bad = {"task_id": "t0", "description": "x", "scope_boundary": [], "dependencies": [], "correlation_id": "c"}
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert(bad, PlannedTask)  # task_class missing


def test_plan_validates_through_handoff_registry():
    payload = {
        "plan_id": "p1",
        "spec_artifact_id": "s1",
        "tasks": [],
        "correlation_id": "corr-1",
        "created_at_millis": 1,
    }
    plan = registry.validate_before_consumption("plan", payload)
    assert isinstance(plan, PlanArtifact)
