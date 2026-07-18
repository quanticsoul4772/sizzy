"""B1.5: Invariant 6 — explore-pass artifacts are validated before consumption."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts import explore  # noqa: F401  (registers "explore_pass")
from devharness.artifacts.explore import ExplorePassArtifact
from devharness.artifacts.registry import HandoffValidationError, validate_before_consumption

_VALID = {
    "explore_pass_id": "e1",
    "repo_root": "/abs/repo",
    "file_tree": [{"path": "src", "kind": "directory", "depth": 1}],
    "dependency_manifests": [],
    "test_signatures": [],
    "ci_configs": [],
    "correlation_id": "corr-1",
    "created_at_millis": 1,
}


def test_valid_payload_passes():
    artifact = validate_before_consumption("explore_pass", _VALID)
    assert isinstance(artifact, ExplorePassArtifact)


def test_missing_required_field_rejected():
    bad = {k: v for k, v in _VALID.items() if k != "repo_root"}
    with pytest.raises(HandoffValidationError) as exc:
        validate_before_consumption("explore_pass", bad)
    assert "repo_root" in str(exc.value)


def test_wrong_type_rejected():
    bad = {**_VALID, "created_at_millis": "not-an-int"}
    with pytest.raises(HandoffValidationError):
        validate_before_consumption("explore_pass", bad)
