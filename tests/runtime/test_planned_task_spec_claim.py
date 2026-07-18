"""B3.2: PlannedTask.spec_claim is additive with default ""; old constructions still work."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import PlannedTask


def test_spec_claim_defaults_empty():
    t = PlannedTask(task_id="t1", task_class="feature", description="d", scope_boundary=[], dependencies=[], correlation_id="c")
    assert t.spec_claim == ""
    assert t.verifier_ref is None  # also still defaulted


def test_spec_claim_set():
    t = PlannedTask(task_id="t1", task_class="feature", description="d", scope_boundary=[], dependencies=[], correlation_id="c",
                    verifier_ref="feature_spec_claim", spec_claim="add foo() returning 42")
    assert t.spec_claim == "add foo() returning 42"


def test_b1_style_construction_unaffected():
    # a pre-B3.2 construction (no spec_claim) must still build
    t = PlannedTask(task_id="t1", task_class="new_project_scaffold", description="scaffold",
                    scope_boundary=["**"], dependencies=[], correlation_id="c", verifier_ref="test_suite")
    assert t.spec_claim == "" and t.verifier_ref == "test_suite"
