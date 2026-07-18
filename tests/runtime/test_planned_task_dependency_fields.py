"""B3.5: PlannedTask gains the five dependency_bump fields, all additive with default ""."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import PlannedTask


def test_dependency_fields_default_empty():
    t = PlannedTask(task_id="t1", task_class="dependency_bump", description="d", scope_boundary=[], dependencies=[], correlation_id="c")
    assert t.dependency_name == "" and t.target_version == "" and t.bump_command == ""
    assert t.manifest_path == "" and t.lockfile_path == ""


def test_dependency_fields_set():
    t = PlannedTask(task_id="t1", task_class="dependency_bump", description="d", scope_boundary=[], dependencies=[], correlation_id="c",
                    verifier_ref="dependency_resolves", dependency_name="requests", target_version="2.31.0",
                    bump_command="pip install requests==2.31.0", manifest_path="pyproject.toml", lockfile_path="requirements.lock")
    assert t.dependency_name == "requests" and t.target_version == "2.31.0"
    assert t.bump_command == "pip install requests==2.31.0"


def test_pre_b3_5_construction_unaffected():
    t = PlannedTask(task_id="t1", task_class="feature", description="d", scope_boundary=["**"], dependencies=[],
                    correlation_id="c", verifier_ref="feature_spec_claim", spec_claim="x")
    assert t.dependency_name == "" and t.spec_claim == "x"
