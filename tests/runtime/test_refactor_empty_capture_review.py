"""Review #4: refactor_behavior_preserving must FAIL closed when no tests were captured.

A pass_fail_command that crashes / collects nothing / targets the wrong dir emits no `<id> pass|fail`
lines, so baseline and post are both empty and `_diff({}, {})` is None — which previously certified
"behaviour preserved" against an EMPTY test set. The verifier now rejects an empty capture.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.verifier.base import VerifierFailed, VerifierOk
from devharness.verifier.builtin.refactor_behavior_preserving import RefactorBehaviorPreservingVerifier


def _git_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "app.py").write_text("x = 1\n")
    run("add", "-A")
    run("commit", "-m", "base")
    return repo


def test_empty_pass_fail_set_fails_closed(tmp_path):
    repo = _git_repo(tmp_path)
    ctx = {"cwd": str(repo), "pass_fail_command": ["python", "-c", "pass"]}  # emits no test lines
    result = asyncio.run(RefactorBehaviorPreservingVerifier().verify(ctx))
    assert isinstance(result, VerifierFailed)
    assert "no test results" in result.reason


def test_nonempty_identical_set_still_passes(tmp_path):
    repo = _git_repo(tmp_path)
    ctx = {"cwd": str(repo), "pass_fail_command": ["python", "-c", "print('t1 pass')"]}
    assert isinstance(asyncio.run(RefactorBehaviorPreservingVerifier().verify(ctx)), VerifierOk)
