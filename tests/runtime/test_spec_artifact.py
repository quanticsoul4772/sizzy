"""B1.1: SpecArtifact validation, required non-empty assumptions, and sign()."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.spec import Assumption, SpecArtifact


def _spec(**overrides) -> SpecArtifact:
    base = dict(
        problem="harness collapses on write authority",
        scope="four-role read-only loop",
        non_goals=["parallel writers"],
        interfaces=["spec artifact", "plan artifact"],
        success_criteria=["signed spec produced"],
        verification_plan="tests + parallax verify",
        assumptions=[Assumption(text="single operator", confidence=0.9, low_confidence_flag=False)],
        correlation_id="corr-1",
    )
    base.update(overrides)
    return SpecArtifact(**base)


def test_fully_populated_is_valid():
    assert _spec().is_valid() is True


def test_empty_assumptions_is_invalid():
    assert _spec(assumptions=[]).is_valid() is False


def test_missing_required_string_is_invalid():
    assert _spec(problem="").is_valid() is False
    assert _spec(verification_plan="").is_valid() is False
    assert _spec(success_criteria=[]).is_valid() is False


def test_sign_returns_signed_copy_and_leaves_original_unchanged():
    spec = _spec()
    signed = spec.sign(signed_by="operator", signed_at_millis=1_700_000_000_000)
    assert signed.signed is True
    assert signed.signed_by == "operator"
    assert signed.signed_at_millis == 1_700_000_000_000
    # original is frozen and unchanged
    assert spec.signed is False
    assert spec.signed_by is None
    assert spec.signed_at_millis is None
