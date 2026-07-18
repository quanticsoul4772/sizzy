"""B2.2: VerifierAttachedGate semantic — refuses missing/unknown, allows registered."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers the falsifiers)
from devharness.gates.base import GateDeny, GateOk
from devharness.gates.verifier_attached import VerifierAttachedGate


def test_refuses_missing_verifier_ref():
    deny = VerifierAttachedGate().check({"verifier_ref": None})
    assert isinstance(deny, GateDeny)
    assert deny.reason == "Task verifier_ref is None"


def test_refuses_unknown_verifier_name():
    deny = VerifierAttachedGate().check({"verifier_ref": "not_a_real_verifier"})
    assert isinstance(deny, GateDeny)
    assert deny.reason == "Task verifier_ref not_a_real_verifier is not registered in FALSIFIERS"


def test_allows_registered_verifier_name():
    assert isinstance(VerifierAttachedGate().check({"verifier_ref": "parallax_verify"}), GateOk)
    assert isinstance(VerifierAttachedGate().check({"verifier_ref": "test_suite"}), GateOk)
