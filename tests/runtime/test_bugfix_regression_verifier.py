"""B3.3: BugfixRegressionVerifier asserts baseline-fails + post-passes + suite-passes."""

import asyncio
import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401
from devharness.verifier.base import VerifierFailed, VerifierOk
from devharness.verifier.builtin.bugfix_regression import BugfixRegressionVerifier
from devharness.verifier.registry import FALSIFIERS

# the regression "test": passes iff app.py declares the fix (return 42)
REGRESSION = ["python", "-c", "import sys; sys.exit(0 if 'return 42' in open('app.py').read() else 1)"]
SUITE_OK = ["python", "-c", "import sys; sys.exit(0)"]
SUITE_FAIL = ["python", "-c", "import sys; sys.exit(1)"]


def _repo(tmp_path, baseline_app):
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "app.py").write_text(baseline_app)
    run("add", "-A")
    run("commit", "-m", "baseline")
    return repo


def _ctx(repo, regression=REGRESSION, suite=SUITE_OK):
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return {"task_id": "t", "correlation_id": "c", "cwd": str(repo),
            "checkpoint": types.SimpleNamespace(git_commit_sha=sha), "regression_command": regression, "test_command": suite}


def test_registered():
    assert "bugfix_regression" in FALSIFIERS


def test_all_axes_pass(tmp_path):
    repo = _repo(tmp_path, "def foo():\n    return 0\n")          # baseline: the bug
    (repo / "app.py").write_text("def foo():\n    return 42\n")   # developer's fix (uncommitted)
    result = asyncio.run(BugfixRegressionVerifier().verify(_ctx(repo)))
    assert isinstance(result, VerifierOk)
    assert result.evidence["baseline_rc"] != 0 and result.evidence["post_rc"] == 0


def test_baseline_should_fail_axis(tmp_path):
    repo = _repo(tmp_path, "def foo():\n    return 42\n")         # baseline already fixed -> no bug
    (repo / "app.py").write_text("def foo():\n    return 42  # tweak\n")
    result = asyncio.run(BugfixRegressionVerifier().verify(_ctx(repo)))
    assert isinstance(result, VerifierFailed) and "baseline_should_fail" in result.reason


def test_post_should_pass_axis(tmp_path):
    repo = _repo(tmp_path, "def foo():\n    return 0\n")          # bug present
    (repo / "app.py").write_text("def foo():\n    return 41\n")   # wrong fix
    result = asyncio.run(BugfixRegressionVerifier().verify(_ctx(repo)))
    assert isinstance(result, VerifierFailed) and "post_should_pass" in result.reason


def test_suite_axis(tmp_path):
    repo = _repo(tmp_path, "def foo():\n    return 0\n")
    (repo / "app.py").write_text("def foo():\n    return 42\n")   # correct fix, but the suite fails
    result = asyncio.run(BugfixRegressionVerifier().verify(_ctx(repo, suite=SUITE_FAIL)))
    assert isinstance(result, VerifierFailed) and "suite_passes" in result.reason


def test_committed_fix_reaches_baseline_via_checkpoint(tmp_path):
    # The OSS reviewer re-runs the verifier AFTER the bot-identity commit (clean tree, `git stash` a no-op).
    # Before the fix, baseline_rc ran against the COMMITTED (already-fixed) tree -> exit 0 ->
    # "baseline_should_fail" wrongly REJECTED a legitimately-fixed OSS bugfix. Now baseline comes from the
    # checkpoint commit (the bug present) -> baseline fails, post passes -> OK.
    repo = _repo(tmp_path, "def foo():\n    return 0\n")          # baseline: the bug
    baseline_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
    (repo / "app.py").write_text("def foo():\n    return 42\n")   # the fix, COMMITTED (like the bot-commit)
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("add", "-A"); run("commit", "-m", "fix committed (like the OSS bot-commit)")
    ctx = {"task_id": "t", "correlation_id": "c", "cwd": str(repo),
           "checkpoint": types.SimpleNamespace(git_commit_sha=baseline_sha),
           "regression_command": REGRESSION, "test_command": SUITE_OK}
    result = asyncio.run(BugfixRegressionVerifier().verify(ctx))
    assert isinstance(result, VerifierOk)
    assert result.evidence["baseline_rc"] != 0 and result.evidence["post_rc"] == 0
