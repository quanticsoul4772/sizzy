"""B1.1: handoff registry + validate_before_consumption."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts import registry
from devharness.artifacts.spec import SpecArtifact

_VALID = {
    "problem": "p",
    "scope": "s",
    "non_goals": [],
    "interfaces": [],
    "success_criteria": ["sc"],
    "verification_plan": "v",
    "assumptions": [{"text": "a", "confidence": 0.5, "low_confidence_flag": False}],
    "correlation_id": "corr-1",
}


def test_spec_registered():
    assert registry.HANDOFF_ARTIFACTS.get("spec") is SpecArtifact


def test_validate_returns_typed_instance():
    artifact = registry.validate_before_consumption("spec", _VALID)
    assert isinstance(artifact, SpecArtifact)
    assert artifact.problem == "p"


def test_validate_rejects_missing_required_field_naming_it():
    bad = {k: v for k, v in _VALID.items() if k != "problem"}
    with pytest.raises(registry.HandoffValidationError) as exc:
        registry.validate_before_consumption("spec", bad)
    assert "problem" in str(exc.value)


def test_validate_rejects_empty_assumptions():
    bad = {**_VALID, "assumptions": []}
    with pytest.raises(registry.HandoffValidationError) as exc:
        registry.validate_before_consumption("spec", bad)
    assert "assumptions" in str(exc.value)


def test_validate_rejects_unregistered_artifact():
    with pytest.raises(registry.HandoffValidationError):
        registry.validate_before_consumption("nope", _VALID)


def test_register_artifact_schema_single_write():
    with pytest.raises(registry.HandoffValidationError):
        registry.register_artifact_schema("spec", SpecArtifact)  # already registered
