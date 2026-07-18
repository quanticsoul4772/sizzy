"""bugfix_regression falsifier (B3.3).

A `bugfix` task's declared verification: a named regression test FAILS at the baseline (so the
bug is demonstrably present) and PASSES after the fix, and the full suite still passes. Three
axes, decision rule is code:
  - baseline_should_fail: the regression test must fail against the baseline checkpoint state.
  - post_should_pass: the regression test must pass against the fixed worktree.
  - suite_passes: the full test suite must pass (no new failure introduced).

Baseline state is reached by stashing the developer's uncommitted changes (HEAD is the B2.4
checkpoint commit); the stash is popped to restore the post-fix worktree before the post checks.
"""

import os
import subprocess

from devharness.verifier.base import Verifier, VerifierFailed, VerifierOk
from devharness.verifier.builtin._baseline import at_baseline
from devharness.verifier.builtin.test_suite import TestSuiteVerifier
from devharness.verifier.class_commands import language_for_test_command, regression_test_files
from devharness.verifier.registry import register_verifier


def _run(command, cwd) -> int:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True).returncode


class BugfixRegressionVerifier(Verifier):
    name = "bugfix_regression"

    def __init__(self, test_suite=None):
        self._test_suite = test_suite or TestSuiteVerifier()

    async def verify(self, context: dict):
        cwd = context["cwd"]
        checkpoint = context.get("checkpoint")
        # rev 0.3.73: fail closed on a missing command — a director-planned bugfix left
        # regression_test_ref empty and the driver derives it from the diff, but if nothing was
        # derivable the caller passes no command; reaching the verifier without one used to KeyError
        # (crash → no terminal → W re-dispatch loop), the dependency_bump WinError-87 shape.
        regression = context.get("regression_command")
        language = language_for_test_command(context.get("test_command"))
        if not regression:
            # name the per-language placement rule — the retry's worker reads this rejection text,
            # and a Rust worker's natural unit #[test] in src/ is exactly what derivation excludes
            # (rev 0.4.9 review catch: without the rule the retry repeats the same miss)
            hint = {
                "rust": " — for a cargo project the regression test must be a NEW direct-child "
                        "tests/*.rs integration-test file (a unit #[test] inside src/ has no "
                        "per-file runner and is not derivable)",
                "python": "",
            }.get(language, f" — {language} bugfixes have no regression derivation yet")
            return VerifierFailed(
                name=self.name,
                reason="regression_command missing — no regression_test_ref on the task and none "
                       "derivable from the realized diff (need exactly one test file in the change)"
                       + hint,
                evidence={},
            )

        # 1. baseline: run the regression at the CHECKPOINT commit (robust to a committed OR uncommitted
        # change — see _baseline.at_baseline; the OSS reviewer re-runs after the bot-commit, a clean tree).
        # The regression test is NEW/MODIFIED in this task, so the baseline stash removes it — overlay its
        # POST content onto the baseline (fix absent) so the test genuinely fails, not vacuously-fails on an
        # absent file (rev 0.3.73). Read the content BEFORE at_baseline stashes the worktree.
        overlay = {}
        for path in regression_test_files(context.get("diff_content") or "", language):
            abspath = os.path.join(cwd, path)
            if os.path.isfile(abspath):
                with open(abspath, encoding="utf-8") as f:
                    overlay[path] = f.read()
        checkpoint_sha = getattr(checkpoint, "git_commit_sha", None)
        baseline_rc = at_baseline(cwd, checkpoint_sha, lambda: _run(regression, cwd), overlay=overlay)

        evidence = {
            "baseline_rc": baseline_rc, "regression_command": regression,
            "checkpoint_sha": getattr(checkpoint, "git_commit_sha", None),
            "baseline_overlay": sorted(overlay),
        }
        if baseline_rc == 0:
            return VerifierFailed(
                name=self.name,
                reason="baseline_should_fail axis failed: the regression test passed at baseline (no bug demonstrated)",
                evidence=evidence,
            )

        # 2. post: the regression test must pass on the fixed worktree
        post_rc = _run(regression, cwd)
        evidence["post_rc"] = post_rc
        if post_rc != 0:
            return VerifierFailed(
                name=self.name,
                reason="post_should_pass axis failed: the regression test still fails after the fix",
                evidence=evidence,
            )

        # 3. suite: the full test suite must still pass
        suite = await self._test_suite.verify(context)
        evidence["suite"] = getattr(suite, "evidence", {})
        if isinstance(suite, VerifierFailed):
            return VerifierFailed(name=self.name, reason=f"suite_passes axis failed: {suite.reason}", evidence=evidence)
        return VerifierOk(name=self.name, evidence=evidence)


register_verifier("bugfix_regression", BugfixRegressionVerifier())
