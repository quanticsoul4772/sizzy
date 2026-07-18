"""B2.3: ACI test runner returns structured results (subprocess mocked)."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.aci.test_runner import TestRunnerActions
from devharness.worktree.isolate import Worktree


class _Proc:
    def __init__(self, returncode):
        self.returncode = returncode
        self.stdout = "11 passed"
        self.stderr = ""


def _runner(tmp_path):
    return TestRunnerActions(worktree=Worktree("t", str(tmp_path), str(tmp_path)))


def test_passing_suite(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0))
    result = _runner(tmp_path).run_tests(["pytest", "-q"])
    assert result["passed"] is True
    assert result["returncode"] == 0
    assert result["command"] == ["pytest", "-q"]
    assert "11 passed" in result["stdout"]


def test_failing_suite(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(1))
    result = _runner(tmp_path).run_tests()
    assert result["passed"] is False
    assert result["command"] == ["pytest", "-q"]  # default
