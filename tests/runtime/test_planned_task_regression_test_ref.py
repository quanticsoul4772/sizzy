"""B3.3: PlannedTask.regression_test_ref is additive with default ""; old constructions work."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import PlannedTask


def test_regression_test_ref_defaults_empty():
    t = PlannedTask(task_id="t1", task_class="bugfix", description="d", scope_boundary=[], dependencies=[], correlation_id="c")
    assert t.regression_test_ref == ""
    assert t.spec_claim == "" and t.verifier_ref is None


def test_regression_test_ref_set():
    t = PlannedTask(task_id="t1", task_class="bugfix", description="d", scope_boundary=[], dependencies=[], correlation_id="c",
                    verifier_ref="bugfix_regression", regression_test_ref="tests/test_bug_42.py")
    assert t.regression_test_ref == "tests/test_bug_42.py"


def test_pre_b3_3_construction_unaffected():
    t = PlannedTask(task_id="t1", task_class="feature", description="d", scope_boundary=["**"], dependencies=[],
                    correlation_id="c", verifier_ref="feature_spec_claim", spec_claim="x")
    assert t.regression_test_ref == "" and t.spec_claim == "x"
