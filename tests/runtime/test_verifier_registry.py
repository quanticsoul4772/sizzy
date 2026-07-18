"""B2.2: falsifier registry — sole writer, single-write, 4 builtins register."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers the 4 builtins at import)
from devharness.verifier.base import Verifier, VerifierOk
from devharness.verifier.registry import FALSIFIERS, VerifierRegistrationError, register_verifier


def test_four_builtins_registered():
    for name in ("parallax_verify", "parallax_check", "parallax_grounded_verify", "test_suite"):
        assert name in FALSIFIERS
        assert isinstance(FALSIFIERS[name], Verifier)


def test_single_write_enforcement():
    with pytest.raises(VerifierRegistrationError):
        register_verifier("test_suite", FALSIFIERS["test_suite"])  # already registered


def test_register_new_then_present():
    class _V(Verifier):
        name = "_temp_verifier"

        async def verify(self, context):
            return VerifierOk(name=self.name)

    register_verifier("_temp_verifier", _V())
    assert "_temp_verifier" in FALSIFIERS
    with pytest.raises(VerifierRegistrationError):
        register_verifier("_temp_verifier", _V())
