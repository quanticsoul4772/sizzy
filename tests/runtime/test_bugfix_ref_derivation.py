"""rev 0.3.73: a director-planned bugfix's regression_test_ref derives from the realized diff, the
verifier fails closed on a missing command, and the baseline overlays the NEW test so its
'bug present at baseline' axis is real, not vacuous.

Live: the first console-driven bugfix (an HTML-converter XSS) carried regression_test_ref='' (only the
operator-injected script flow ever set it); the verifier did context['regression_command'] -> KeyError,
dispatch died with no terminal, W re-crashed. Deriving + failing-closed alone would have been WORSE
than the crash: the new regression test is stashed away at baseline, so pytest exits 'file not found'
and baseline_should_fail passes VACUOUSLY -> a silent false-certification. The overlay closes that.
"""

import asyncio
import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401
from devharness.verifier.base import VerifierFailed, VerifierOk
from devharness.verifier.builtin.bugfix_regression import BugfixRegressionVerifier
from devharness.verifier.class_commands import derive_regression_test_ref, regression_test_files


def _diff(*paths):
    lines = []
    for p in paths:
        lines += [f"diff --git a/{p} b/{p}", f"--- a/{p}", f"+++ b/{p}", "@@ -0,0 +1 @@", "+x = 1"]
    return "\n".join(lines) + "\n"


def test_derive_picks_the_single_test_file():
    d = _diff("pkg/_inline.py", "tests/test_inline.py")
    assert regression_test_files(d) == ["tests/test_inline.py"]
    assert derive_regression_test_ref(d) == "tests/test_inline.py"


def test_derive_matches_pytest_naming_and_tests_dir():
    assert regression_test_files(_diff("pkg/thing_test.py")) == ["pkg/thing_test.py"]
    assert regression_test_files(_diff("tests/deep/check.py")) == ["tests/deep/check.py"]
    assert regression_test_files(_diff("src/app.py")) == []  # not a test file


def test_derive_empty_when_zero_or_multiple():
    assert derive_regression_test_ref(_diff("src/app.py")) == ""  # no test file
    assert derive_regression_test_ref(_diff("tests/test_a.py", "tests/test_b.py")) == ""  # ambiguous


def test_verifier_fails_closed_without_a_command():
    # the exact crash: no regression_command in context. Must be VerifierFailed, never KeyError.
    result = asyncio.run(BugfixRegressionVerifier().verify(
        {"cwd": ".", "checkpoint": None, "diff_content": ""}))
    assert isinstance(result, VerifierFailed)
    assert "regression_command missing" in result.reason


def _repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init", "-q")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "app.py").write_text("def bug():\n    return 1\n")  # unfixed: returns 1
    run("add", "-A")
    run("commit", "-q", "-m", "base (buggy)")
    return repo, run


def _ctx(repo, diff, checkpoint_sha):
    return {
        "cwd": str(repo), "diff_content": diff,
        "checkpoint": types.SimpleNamespace(git_commit_sha=checkpoint_sha),
        "test_command": ["python", "-m", "pytest", "tests", "-q"],
        "regression_command": ["python", "-m", "pytest", "tests/test_bug.py", "-q", "-p", "no:cacheprovider"],
    }


def test_new_test_overlaid_at_baseline_is_not_vacuous(tmp_path):
    # the worker fixed app.py (returns 2) AND wrote a NEW regression test asserting 2. At baseline the
    # test is stashed away; without the overlay pytest would exit 'file not found' (vacuous pass). WITH
    # the overlay the test runs against the UNFIXED code and genuinely fails -> baseline_should_fail real.
    repo, run = _repo(tmp_path)
    checkpoint = run("rev-parse", "HEAD").stdout.strip()
    # worker's post state (uncommitted): the fix + the new test
    (repo / "app.py").write_text("def bug():\n    return 2\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_bug.py").write_text(
        "from app import bug\ndef test_bug():\n    assert bug() == 2\n")
    diff = _diff("app.py", "tests/test_bug.py")

    result = asyncio.run(BugfixRegressionVerifier().verify(_ctx(repo, diff, checkpoint)))
    assert isinstance(result, VerifierOk), result
    assert result.evidence["baseline_rc"] != 0  # the test failed at baseline (bug present) — not vacuous
    assert result.evidence["baseline_overlay"] == ["tests/test_bug.py"]
    # the worktree is restored intact after the overlay dance
    assert (repo / "tests" / "test_bug.py").read_text().endswith("assert bug() == 2\n")
    assert (repo / "app.py").read_text() == "def bug():\n    return 2\n"


def test_baseline_overlay_catches_a_test_that_passes_at_baseline(tmp_path):
    # a "regression test" that passes even against the UNFIXED code demonstrates no bug — the overlay
    # makes baseline_should_fail correctly REJECT it (it would falsely pass if the file were just absent).
    repo, run = _repo(tmp_path)
    checkpoint = run("rev-parse", "HEAD").stdout.strip()
    (repo / "app.py").write_text("def bug():\n    return 2\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_bug.py").write_text(
        "from app import bug\ndef test_bug():\n    assert bug() in (1, 2)\n")  # passes unfixed AND fixed
    diff = _diff("app.py", "tests/test_bug.py")

    result = asyncio.run(BugfixRegressionVerifier().verify(_ctx(repo, diff, checkpoint)))
    assert isinstance(result, VerifierFailed)
    assert "baseline_should_fail" in result.reason
