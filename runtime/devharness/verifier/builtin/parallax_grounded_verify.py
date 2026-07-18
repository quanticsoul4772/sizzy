"""parallax.grounded_verify falsifier (B2.2) — claim against verbatim named source."""

from devharness.verifier.base import Verifier, VerifierFailed, VerifierOk
from devharness.verifier.builtin._common import looks_like_prompt_injection, parallax_passed
from devharness.verifier.registry import register_verifier


class ParallaxGroundedVerifyVerifier(Verifier):
    name = "parallax_grounded_verify"

    async def verify(self, context: dict):
        client = context["parallax"]
        claim = context.get("claim", "")
        # F4 (rev 0.3.67): the claim can be untrusted external text on the OSS reviewer's default path.
        # If it carries injection-directive structure the verdict is untrustworthy — fail SAFE.
        if looks_like_prompt_injection(claim):
            return VerifierFailed(name=self.name, reason="claim carries prompt-injection directive structure",
                                  evidence={"tool": "parallax.grounded_verify", "injection_guard": True})
        result = await client.grounded_verify(claim=claim, sources=context.get("sources", []))
        evidence = {"tool": "parallax.grounded_verify", "sources": context.get("sources", []), "output": result.output, "cost_usd": result.cost_usd}
        if parallax_passed(result):
            return VerifierOk(name=self.name, evidence=evidence)
        return VerifierFailed(name=self.name, reason="named source does not support the claim", evidence=evidence)


register_verifier("parallax_grounded_verify", ParallaxGroundedVerifyVerifier())
