"""B2.2: TestSuiteVerifier — exit 0 passes, non-zero fails (subprocess mocked)."""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.verifier.base import VerifierFailed, VerifierOk
from devharness.verifier.builtin.test_suite import TestSuiteVerifier


class _Proc:
    def __init__(self, returncode):
        self.returncode = returncode
        self.stdout = "out"
        self.stderr = "err"


def test_exit_zero_passes(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0))
    result = asyncio.run(TestSuiteVerifier().verify({"test_command": ["pytest", "-q"]}))
    assert isinstance(result, VerifierOk)
    assert result.evidence["returncode"] == 0


def test_nonzero_fails(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(1))
    result = asyncio.run(TestSuiteVerifier().verify({"test_command": ["pytest", "-q"]}))
    assert isinstance(result, VerifierFailed)
    assert "exited 1" in result.reason
    assert result.evidence["returncode"] == 1
