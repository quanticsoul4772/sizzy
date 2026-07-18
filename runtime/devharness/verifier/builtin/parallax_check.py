"""parallax.check falsifier (B2.2) — computable claims; the deterministic engine decides."""

from devharness.verifier.base import Verifier, VerifierFailed, VerifierOk
from devharness.verifier.builtin._common import looks_like_prompt_injection, parallax_passed
from devharness.verifier.registry import register_verifier


class ParallaxCheckVerifier(Verifier):
    name = "parallax_check"

    async def verify(self, context: dict):
        client = context["parallax"]
        claim = context.get("claim", "")
        # F4 (rev 0.3.67): check takes only a `claim` (no context-separation seam), and on the OSS
        # reviewer's default-verifier path the claim can be untrusted external text. If it carries
        # injection-directive structure the verdict is untrustworthy — fail SAFE (sibling of parallax_verify).
        if looks_like_prompt_injection(claim):
            return VerifierFailed(name=self.name, reason="claim carries prompt-injection directive structure",
                                  evidence={"tool": "parallax.check", "injection_guard": True})
        result = await client.check(claim=claim)
        evidence = {"tool": "parallax.check", "output": result.output, "cost_usd": result.cost_usd}
        if parallax_passed(result):
            return VerifierOk(name=self.name, evidence=evidence)
        return VerifierFailed(name=self.name, reason="parallax.check found the claim inconsistent", evidence=evidence)


register_verifier("parallax_check", ParallaxCheckVerifier())
