"""B4.2: workflow_guard — denies CI/CD workflow writes; override allows."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.gates.base import GateDeny, GateOk
from devharness.gates.workflow_guard import WorkflowGuard


def _g():
    return WorkflowGuard()


def test_denies_github_workflow():
    r = _g().check({"touched_paths": ["src/app.py", ".github/workflows/ci.yml"]})
    assert isinstance(r, GateDeny) and "workflow_modified" in r.reason
    assert r.evidence["matched_paths"] == [".github/workflows/ci.yml"]


def test_denies_other_ci_systems():
    for path in (".github/actions/build/action.yml", ".gitlab-ci.yml", ".buildkite/pipeline.yml", ".circleci/config.yml"):
        assert isinstance(_g().check({"touched_paths": [path]}), GateDeny)


def test_clean_paths_pass():
    assert isinstance(_g().check({"touched_paths": ["src/app.py", "README.md"]}), GateOk)
    assert isinstance(_g().check({"touched_paths": []}), GateOk)


def test_multiple_matches_in_evidence():
    r = _g().check({"touched_paths": [".github/workflows/ci.yml", ".github/workflows/release.yml"]})
    assert isinstance(r, GateDeny) and len(r.evidence["matched_paths"]) == 2


def test_override_allows():
    r = _g().check({"touched_paths": [".github/workflows/ci.yml"], "workflow_guard_override": True})
    assert isinstance(r, GateOk) and r.reason == "workflow_modified_with_override"
