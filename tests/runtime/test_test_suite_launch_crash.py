"""test_suite must not score a test-runner launch-crash as a test failure.

The M2 re-run hit exit 3221225794 (0xC0000142, STATUS_DLL_INIT_FAILED) under process pressure —
the runner never launched — and the verifier counted it as a failed test, rewinding good work.
A launch-crash (fatal OS exit, no test output) is now retried; a persistent one raises an
infrastructure error instead of a false failure. A genuine test failure (output present) is unchanged.
"""

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.verifier.base import VerifierFailed, VerifierOk
from devharness.verifier.builtin import test_suite as ts


@dataclass
class _Proc:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _patch_runs(monkeypatch, procs):
    """Feed a sequence of fake subprocess results; record how many times the command ran."""
    seq = iter(procs)
    calls = {"n": 0}

    def fake_run(command, cwd=None, capture_output=True, text=True):
        calls["n"] += 1
        return next(seq)

    monkeypatch.setattr(ts.subprocess, "run", fake_run)
    monkeypatch.setattr(ts.time, "sleep", lambda *_: None)
    return calls


def test_launch_crash_is_retried_then_raises(monkeypatch):
    # crashes on launch every attempt (fatal code, no output) -> retried _MAX_ATTEMPTS, then raises
    calls = _patch_runs(monkeypatch, [_Proc(3221225794, "", "")] * ts.TestSuiteVerifier._MAX_ATTEMPTS)
    with pytest.raises(RuntimeError, match="failed to launch"):
        asyncio.run(ts.TestSuiteVerifier().verify({"test_command": ["pytest"]}))
    assert calls["n"] == ts.TestSuiteVerifier._MAX_ATTEMPTS


def test_launch_crash_then_recovers(monkeypatch):
    # first attempt crashes on launch, retry actually runs the tests and passes
    calls = _patch_runs(monkeypatch, [_Proc(3221225794, "", ""), _Proc(0, "5 passed", "")])
    result = asyncio.run(ts.TestSuiteVerifier().verify({"test_command": ["pytest"]}))
    assert isinstance(result, VerifierOk)
    assert calls["n"] == 2


def test_real_test_failure_is_not_retried(monkeypatch):
    # exit 1 WITH test output is a genuine failure — runs once, fails (not a launch-crash)
    calls = _patch_runs(monkeypatch, [_Proc(1, "1 failed, 4 passed", "")])
    result = asyncio.run(ts.TestSuiteVerifier().verify({"test_command": ["pytest"]}))
    assert isinstance(result, VerifierFailed)
    assert calls["n"] == 1


def test_pass_is_unchanged(monkeypatch):
    _patch_runs(monkeypatch, [_Proc(0, "5 passed", "")])
    result = asyncio.run(ts.TestSuiteVerifier().verify({"test_command": ["pytest"]}))
    assert isinstance(result, VerifierOk)
