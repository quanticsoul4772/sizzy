"""B1.3: the three graduated boot-checks pass and fail closed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.gates import registry
from devharness.gates.base import Gate, GateOk
import devharness.gates.spec_signed  # noqa: F401  (registers the gate)


def test_three_registered_under_c12_and_c9():
    names = boot.registered_check_names()
    assert "check_spec_gate_present" in names
    assert "check_build_state_requires_signed_spec" in names
    assert "check_gate_deny_envelope_shape" in names
    assert boot.REQUIRED_GATES["check_spec_gate_present"] == "C12"
    assert boot.REQUIRED_GATES["check_build_state_requires_signed_spec"] == "C12"
    assert boot.REQUIRED_GATES["check_gate_deny_envelope_shape"] == "C9"


def test_all_three_pass():
    assert boot.check_spec_gate_present() is True
    assert boot.check_build_state_requires_signed_spec() is True
    assert boot.check_gate_deny_envelope_shape() is True


def test_spec_gate_present_fails_closed_when_unregistered(monkeypatch):
    monkeypatch.delitem(registry.GATES, "spec_signed_gate")
    with pytest.raises(boot.BootError):
        boot.check_spec_gate_present()


def test_build_requires_signed_spec_fails_closed_when_gate_always_ok(monkeypatch):
    class AlwaysOk(Gate):
        name = "spec_signed_gate"

        def check(self, context):
            return GateOk()

    monkeypatch.setitem(registry.GATES, "spec_signed_gate", AlwaysOk())
    with pytest.raises(boot.BootError):
        boot.check_build_state_requires_signed_spec()


def test_deny_envelope_shape_fails_closed_on_bad_gate():
    from types import SimpleNamespace

    class BadDenyGate(Gate):
        name = "bad"

        def check(self, context):
            return SimpleNamespace(reason="", purpose="", fix="")  # empty envelope

    with pytest.raises(boot.BootError):
        boot.check_gate_deny_envelope_shape(gates={"bad": BadDenyGate()})
