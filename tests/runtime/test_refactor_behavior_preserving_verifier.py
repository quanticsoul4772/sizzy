"""B3.4: RefactorBehaviorPreservingVerifier — pass/fail set must be identical pre/post."""

import asyncio
import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401
from devharness.verifier.base import VerifierFailed, VerifierOk
from devharness.verifier.builtin.refactor_behavior_preserving import RefactorBehaviorPreservingVerifier
from devharness.verifier.registry import FALSIFIERS

# the suite: test_foo passes iff foo() == 42 (behaviour, not source text); test_bar is known-failing
_RUN_TESTS = (
    "import sys\n"
    "sys.path.insert(0, '.')\n"
    "try:\n"
    "    import app\n"
    "    foo_ok = app.foo() == 42\n"
    "except Exception:\n"
    "    foo_ok = False\n"
    "print('test_foo', 'pass' if foo_ok else 'fail')\n"
    "print('test_bar', 'fail')\n"
)
PASS_FAIL = ["python", "-B", "run_tests.py"]


def _repo(tmp_path, app_src, run_tests=_RUN_TESTS):
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "app.py").write_text(app_src)
    (repo / "run_tests.py").write_text(run_tests)
    run("add", "-A")
    run("commit", "-m", "baseline")
    return repo


def _ctx(repo):
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return {"task_id": "t", "correlation_id": "c", "cwd": str(repo),
            "checkpoint": types.SimpleNamespace(git_commit_sha=sha), "pass_fail_command": PASS_FAIL}


def test_registered():
    assert "refactor_behavior_preserving" in FALSIFIERS


def test_behavior_preserving_is_ok(tmp_path):
    repo = _repo(tmp_path, "def foo():\n    return 42\n")
    # a behaviour-preserving refactor: restructured, foo() still returns 42
    (repo / "app.py").write_text("def foo():\n    value = 42  # refactored\n    return value\n")
    result = asyncio.run(RefactorBehaviorPreservingVerifier().verify(_ctx(repo)))
    assert isinstance(result, VerifierOk)
    assert result.evidence["baseline"] == {"test_foo": True, "test_bar": False}
    assert result.evidence["post"] == {"test_foo": True, "test_bar": False}


def test_pass_to_fail_axis(tmp_path):
    repo = _repo(tmp_path, "def foo():\n    return 42\n")
    (repo / "app.py").write_text("def foo():\n    return 99\n")  # behaviour changed
    result = asyncio.run(RefactorBehaviorPreservingVerifier().verify(_ctx(repo)))
    assert isinstance(result, VerifierFailed) and "pass_to_fail" in result.reason
    assert result.evidence["test_ids"] == ["test_foo"]


def test_fail_to_pass_axis(tmp_path):
    repo = _repo(tmp_path, "def foo():\n    return 0\n")  # test_foo fails at baseline
    (repo / "app.py").write_text("def foo():\n    return 42\n")  # now passes -> behaviour changed
    result = asyncio.run(RefactorBehaviorPreservingVerifier().verify(_ctx(repo)))
    assert isinstance(result, VerifierFailed) and "fail_to_pass" in result.reason


def test_test_added_axis(tmp_path):
    repo = _repo(tmp_path, "def foo():\n    return 42\n")
    # the "refactor" changes the suite itself, adding a test -> set differs
    (repo / "run_tests.py").write_text(_RUN_TESTS + "print('test_baz', 'pass')\n")
    result = asyncio.run(RefactorBehaviorPreservingVerifier().verify(_ctx(repo)))
    assert isinstance(result, VerifierFailed) and "test_added" in result.reason
    assert result.evidence["test_ids"] == ["test_baz"]


def test_test_removed_axis(tmp_path):
    repo = _repo(tmp_path, "def foo():\n    return 42\n")
    reduced = "import sys\nsys.path.insert(0, '.')\nimport app\nprint('test_foo', 'pass' if app.foo() == 42 else 'fail')\n"
    (repo / "run_tests.py").write_text(reduced)  # test_bar removed from the suite
    result = asyncio.run(RefactorBehaviorPreservingVerifier().verify(_ctx(repo)))
    assert isinstance(result, VerifierFailed) and "test_removed" in result.reason
    assert result.evidence["test_ids"] == ["test_bar"]


def _commit(repo, msg):
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("add", "-A"); run("commit", "-m", msg)


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _ctx_ckpt(repo, sha):
    return {"task_id": "t", "correlation_id": "c", "cwd": str(repo),
            "checkpoint": types.SimpleNamespace(git_commit_sha=sha), "pass_fail_command": PASS_FAIL}


def test_committed_change_reaches_baseline_via_checkpoint(tmp_path):
    # The OSS reviewer re-runs the verifier AFTER the bot-identity commit, so the worktree is CLEAN and
    # `git stash` is a no-op. The baseline MUST come from the checkpoint commit, not the committed tree —
    # before the fix this certified vacuously (baseline == post). Now it catches the behaviour change.
    repo = _repo(tmp_path, "def foo():\n    return 42\n")
    baseline_sha = _head(repo)
    (repo / "app.py").write_text("def foo():\n    return 99\n")  # behaviour changed, then COMMITTED
    _commit(repo, "refactor committed (like the OSS bot-commit)")
    result = asyncio.run(RefactorBehaviorPreservingVerifier().verify(_ctx_ckpt(repo, baseline_sha)))
    assert isinstance(result, VerifierFailed) and "pass_to_fail" in result.reason
    assert result.evidence["baseline"] == {"test_foo": True, "test_bar": False}
    assert result.evidence["post"] == {"test_foo": False, "test_bar": False}


def test_committed_behavior_preserving_still_passes(tmp_path):
    repo = _repo(tmp_path, "def foo():\n    return 42\n")
    baseline_sha = _head(repo)
    (repo / "app.py").write_text("def foo():\n    v = 42  # refactored\n    return v\n")
    _commit(repo, "behaviour-preserving refactor committed")
    result = asyncio.run(RefactorBehaviorPreservingVerifier().verify(_ctx_ckpt(repo, baseline_sha)))
    assert isinstance(result, VerifierOk)
    # HEAD is restored to the committed (post) state after baseline capture
    assert _head(repo) != baseline_sha
