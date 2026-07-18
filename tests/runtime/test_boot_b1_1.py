"""B1.1: the two graduated C13 handoff boot-checks pass and fail closed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.artifacts import registry


def test_both_registered_under_c13():
    names = boot.registered_check_names()
    assert "check_handoff_artifact_schema_registered" in names
    assert "check_handoff_artifact_validated_before_consumption" in names
    assert boot.REQUIRED_GATES["check_handoff_artifact_schema_registered"] == "C13"
    assert boot.REQUIRED_GATES["check_handoff_artifact_validated_before_consumption"] == "C13"


def test_schema_registered_passes():
    assert boot.check_handoff_artifact_schema_registered() is True


def test_schema_registered_fails_closed_when_unregistered(monkeypatch):
    monkeypatch.delitem(registry.HANDOFF_ARTIFACTS, "spec")
    with pytest.raises(boot.BootError):
        boot.check_handoff_artifact_schema_registered()


def test_validation_check_passes():
    assert boot.check_handoff_artifact_validated_before_consumption() is True


def test_validation_check_fails_closed_when_validation_broken(monkeypatch):
    # simulate a validator that accepts anything -> the boot check must fail closed
    monkeypatch.setattr(registry, "validate_before_consumption", lambda name, payload: payload)
    with pytest.raises(boot.BootError):
        boot.check_handoff_artifact_validated_before_consumption()
