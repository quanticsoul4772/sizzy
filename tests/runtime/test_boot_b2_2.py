"""B2.2: the two graduated C8 boot-checks pass and fail closed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.gates import registry as gate_registry
import devharness.gates.verifier_attached  # noqa: F401  (registers the gate)
from devharness.verifier.base import Verifier, VerifierOk


def test_both_registered_under_c8():
    names = boot.registered_check_names()
    assert "check_verifier_attached_gate_registered" in names
    assert "check_verifier_decision_rule_is_code" in names
    assert boot.REQUIRED_GATES["check_verifier_attached_gate_registered"] == "C8"
    assert boot.REQUIRED_GATES["check_verifier_decision_rule_is_code"] == "C8"


def test_both_pass():
    assert boot.check_verifier_attached_gate_registered() is True
    assert boot.check_verifier_decision_rule_is_code() is True


def test_gate_check_fails_closed_when_unregistered(monkeypatch):
    monkeypatch.delitem(gate_registry.GATES, "verifier_attached_gate")
    with pytest.raises(boot.BootError):
        boot.check_verifier_attached_gate_registered()


def test_decision_rule_fails_closed_on_lambda_verify():
    class _LambdaRule(Verifier):
        name = "_bad_lambda"
        verify = lambda self, context: VerifierOk(name="_bad_lambda")  # not a code verify() method

    with pytest.raises(boot.BootError):
        boot.check_verifier_decision_rule_is_code(falsifiers={"_bad_lambda": _LambdaRule()})


def test_decision_rule_fails_closed_on_config_decision_attr():
    class _ConfigRule(Verifier):
        name = "_bad_config"

        def __init__(self):
            self.decision = lambda: True  # config/model-supplied decision

        async def verify(self, context):
            return VerifierOk(name=self.name)

    with pytest.raises(boot.BootError):
        boot.check_verifier_decision_rule_is_code(falsifiers={"_bad_config": _ConfigRule()})
