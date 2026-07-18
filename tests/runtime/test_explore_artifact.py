"""B1.5: ExplorePassArtifact + nested structs + handoff registration."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts import registry
from devharness.artifacts.explore import (
    CIConfig,
    DependencyManifest,
    ExplorePassArtifact,
    FileTreeEntry,
)
from devharness.artifacts.explore import TestSignature as SignatureStruct  # aliased: avoid pytest test-class collection


def test_explore_pass_registered_in_handoff():
    assert registry.HANDOFF_ARTIFACTS.get("explore_pass") is ExplorePassArtifact


def test_nested_structs_validate():
    assert msgspec.convert({"path": "src", "kind": "directory", "depth": 1}, FileTreeEntry).kind == "directory"
    dm = msgspec.convert(
        {"path": "pyproject.toml", "manifest_kind": "pyproject", "detected_frameworks": ["fastapi"]}, DependencyManifest
    )
    assert dm.detected_frameworks == ["fastapi"]
    assert msgspec.convert({"path": "tests", "test_framework": "pytest"}, SignatureStruct).test_framework == "pytest"
    assert msgspec.convert({"path": ".github/workflows/ci.yml", "ci_kind": "github_actions"}, CIConfig).ci_kind == "github_actions"


def test_explore_pass_validates_required_fields():
    artifact = ExplorePassArtifact(
        explore_pass_id="e1",
        repo_root="/abs/repo",
        file_tree=[FileTreeEntry(path="src", kind="directory", depth=1)],
        dependency_manifests=[],
        test_signatures=[],
        ci_configs=[],
        correlation_id="corr-1",
        created_at_millis=1,
    )
    assert artifact.explore_pass_id == "e1"


def test_missing_required_field_rejected():
    bad = {"explore_pass_id": "e1", "file_tree": [], "dependency_manifests": [], "test_signatures": [], "ci_configs": [], "correlation_id": "c", "created_at_millis": 1}
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert(bad, ExplorePassArtifact)  # repo_root missing
