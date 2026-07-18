"""B4.2.5: SandboxLauncher interface + SandboxResult struct + containment error."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.sandbox.base import SandboxContainmentError, SandboxLauncher, SandboxResult


def test_launcher_is_abstract():
    with pytest.raises(TypeError):
        SandboxLauncher()  # exec is abstract


def test_result_struct_frozen_kw_only():
    r = SandboxResult(returncode=0, stdout="out", stderr="", contained=True)
    assert r.returncode == 0 and r.contained is True
    with pytest.raises(AttributeError):
        r.returncode = 1
    with pytest.raises(TypeError):
        SandboxResult(0, "out", "", True)  # positional rejected (kw_only)


def test_result_roundtrip():
    r = SandboxResult(returncode=3, stdout="o", stderr="e", contained=False)
    assert msgspec.convert(msgspec.to_builtins(r), SandboxResult) == r


def test_containment_error_is_runtime_error():
    assert issubclass(SandboxContainmentError, RuntimeError)
