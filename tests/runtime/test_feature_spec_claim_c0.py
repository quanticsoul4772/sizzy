"""#C0: feature_spec_claim verifies the REALIZED diff, not the proposal claim in isolation.

Found by running a real feature through the loop: parallax.verify(spec_claim) rejects every feature
because spec_claim is a forward-looking "implement X" proposal with no evidence. The verifier now
embeds the realized diff as evidence so parallax judges the actual change.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.verifier.base import VerifierFailed, VerifierOk
from devharness.verifier.builtin.feature_spec_claim import FeatureSpecClaimVerifier

_TEST_HUNK = ("diff --git a/tests/test_x.py b/tests/test_x.py\n"
              "+++ b/tests/test_x.py\n+def test_x():\n+    pass\n")


class _OkSuite:
    async def verify(self, ctx):
        return VerifierOk(name="test_suite", evidence={})


class _RecordingParallaxVerifier:
    def __init__(self):
        self.claim = None
        self.untrusted = None

    async def verify(self, ctx):
        self.claim = ctx.get("claim")
        self.untrusted = ctx.get("untrusted_context")
        return VerifierOk(name="parallax_verify", evidence={})


def test_feature_spec_claim_embeds_the_realized_diff():
    pv = _RecordingParallaxVerifier()
    verifier = FeatureSpecClaimVerifier(test_suite=_OkSuite(), parallax_verify=pv)
    # "+def check(): pass" isn't test_-prefixed, so a qualifying test hunk is concatenated alongside it
    # (not substituted) to clear the test_coverage axis first.
    ctx = {"spec_claim": "add an orphaned-tiles component check",
           "diff_content": _TEST_HUNK + "+def check(): pass",
           "task_id": "t", "correlation_id": "c"}
    result = asyncio.run(verifier.verify(ctx))
    assert isinstance(result, VerifierOk)
    # C0: parallax judges the REALIZED diff (not the bare proposal). Injection fix: the spec claim is the
    # trusted assertion; the untrusted diff is forwarded as the SEPARATE context, not concatenated in.
    assert "add an orphaned-tiles component check" in pv.claim
    assert "+def check(): pass" in pv.untrusted          # the diff reaches parallax as untrusted context
    assert "+def check(): pass" not in pv.claim          # NOT inside the assertion
    assert "diff" in pv.claim.lower()                    # the claim still references the context diff


def test_feature_spec_claim_now_fails_at_test_coverage_when_no_diff():
    # test_coverage is unconditional (rev 0.3.49): no diff_content means no test coverage by
    # construction, so parallax is never reached at all -- the prior "no diff -> bare claim" back-compat
    # behavior no longer holds for this verifier (same category as the spec_criteria-axis test's shift).
    pv = _RecordingParallaxVerifier()
    verifier = FeatureSpecClaimVerifier(test_suite=_OkSuite(), parallax_verify=pv)
    result = asyncio.run(verifier.verify({"spec_claim": "add a check"}))
    assert isinstance(result, VerifierFailed)
    assert "test_coverage axis" in result.reason
    assert pv.claim is None  # parallax never reached
