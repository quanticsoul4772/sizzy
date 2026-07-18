"""B3.2: FeatureSpecClaimVerifier composes test_suite + parallax.verify; either axis fails it."""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registration side effect)
from devharness.verifier.base import VerifierFailed, VerifierOk
from devharness.verifier.builtin.feature_spec_claim import FeatureSpecClaimVerifier
from devharness.verifier.registry import FALSIFIERS


class _Result:
    def __init__(self, passed):
        self.output = {"verified": passed}
        self.cost_usd = 0.0
        self.is_error = False


class _FakeParallax:
    def __init__(self, passed):
        self._passed = passed

    async def verify(self, claim, context=""):
        return _Result(self._passed)


def _proc(returncode):
    return type("P", (), {"returncode": returncode, "stdout": "out", "stderr": "err"})()


_QUALIFYING_DIFF = ("diff --git a/tests/test_foo.py b/tests/test_foo.py\n"
                    "+++ b/tests/test_foo.py\n+def test_foo():\n+    assert True\n")


def _ctx(parallax_passed):
    return {"task_id": "t1", "correlation_id": "c", "test_command": ["pytest"], "cwd": ".",
            "parallax": _FakeParallax(parallax_passed), "spec_claim": "foo returns 42",
            "diff_content": _QUALIFYING_DIFF}


def test_registered():
    assert "feature_spec_claim" in FALSIFIERS


def test_both_pass_is_ok(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0))
    result = asyncio.run(FeatureSpecClaimVerifier().verify(_ctx(parallax_passed=True)))
    assert isinstance(result, VerifierOk)
    assert "test_suite" in result.evidence and "parallax_verify" in result.evidence


def test_test_suite_axis_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(1))  # suite fails
    result = asyncio.run(FeatureSpecClaimVerifier().verify(_ctx(parallax_passed=True)))
    assert isinstance(result, VerifierFailed) and "test_suite axis" in result.reason


def test_spec_claim_axis_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _proc(0))  # suite passes
    result = asyncio.run(FeatureSpecClaimVerifier().verify(_ctx(parallax_passed=False)))  # claim refuted
    assert isinstance(result, VerifierFailed) and "spec_claim axis" in result.reason
