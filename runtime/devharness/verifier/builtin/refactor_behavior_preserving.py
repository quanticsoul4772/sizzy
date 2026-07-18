"""refactor_behavior_preserving falsifier (B3.4).

A `refactor` task's declared verification: the test suite's per-test pass/fail set is identical
pre- and post-refactor (wide touch permitted, behavior must hold). Decision rule is code.

The pass/fail set is captured by running ``pass_fail_command`` (which prints one ``test_id pass``
or ``test_id fail`` line per test) at the baseline checkpoint state (reached by stashing the
developer's uncommitted changes, including untracked, so HEAD = the B2.4 checkpoint commit) and
again at the post-refactor state. A difference fails the verifier with the failing axis named:
test_added / test_removed / pass_to_fail / fail_to_pass, plus the differing test_ids in evidence.
"""

import subprocess

from devharness.verifier.base import Verifier, VerifierFailed, VerifierOk
from devharness.verifier.builtin._baseline import at_baseline
from devharness.verifier.registry import register_verifier

_PASS_WORDS = {"pass", "passed", "ok", "true", "1"}


def _capture(command, cwd) -> dict:
    """Run the pass/fail command; parse `test_id pass|fail` lines into {test_id: bool}."""
    out = subprocess.run(command, cwd=cwd, capture_output=True, text=True).stdout
    result = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            result[parts[0]] = parts[1].strip().lower() in _PASS_WORDS
    return result


def _diff(baseline: dict, post: dict):
    """Return (axis, [test_ids]) for the first divergence, or None if the sets are identical."""
    added = sorted(set(post) - set(baseline))
    if added:
        return "test_added", added
    removed = sorted(set(baseline) - set(post))
    if removed:
        return "test_removed", removed
    pass_to_fail = sorted(t for t in baseline if baseline[t] and not post[t])
    if pass_to_fail:
        return "pass_to_fail", pass_to_fail
    fail_to_pass = sorted(t for t in baseline if not baseline[t] and post[t])
    if fail_to_pass:
        return "fail_to_pass", fail_to_pass
    return None


class RefactorBehaviorPreservingVerifier(Verifier):
    name = "refactor_behavior_preserving"

    async def verify(self, context: dict):
        cwd = context["cwd"]
        command = context["pass_fail_command"]
        checkpoint = context.get("checkpoint")

        # baseline is captured at the CHECKPOINT commit (robust to a committed OR uncommitted change — see
        # _baseline.at_baseline); post is captured against the current worktree.
        checkpoint_sha = getattr(checkpoint, "git_commit_sha", None)
        baseline = at_baseline(cwd, checkpoint_sha, lambda: _capture(command, cwd))
        post = _capture(command, cwd)

        evidence = {"baseline": baseline, "post": post, "checkpoint_sha": getattr(checkpoint, "git_commit_sha", None)}
        # Fail closed if NO tests were captured on either side: an empty pass/fail set means the runner
        # never ran (wrong test target, pytest missing/crashed, collection error, half-written XML). With
        # both empty, _diff returns None — certifying "behaviour preserved" against zero tests. A real
        # refactor must demonstrate a non-empty, identical pass/fail set, not the absence of evidence.
        if not baseline and not post:
            return VerifierFailed(
                name=self.name,
                reason="pass_fail_command produced no test results on either baseline or post — the test "
                       "runner did not run (cannot assert behaviour preserved against an empty test set)",
                evidence=evidence,
            )
        diff = _diff(baseline, post)
        if diff is None:
            return VerifierOk(name=self.name, evidence=evidence)
        axis, test_ids = diff
        evidence["axis"] = axis
        evidence["test_ids"] = test_ids
        return VerifierFailed(
            name=self.name,
            reason=f"{axis} axis failed: refactor changed the test pass/fail set for {test_ids}",
            evidence=evidence,
        )


register_verifier("refactor_behavior_preserving", RefactorBehaviorPreservingVerifier())
