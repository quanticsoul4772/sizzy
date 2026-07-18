"""parallax.verify falsifier (B2.2)."""

from devharness.verifier.base import Verifier, VerifierFailed, VerifierOk
from devharness.verifier.builtin._common import parallax_passed
from devharness.verifier.registry import register_verifier


class ParallaxVerifyVerifier(Verifier):
    name = "parallax_verify"

    async def verify(self, context: dict):
        client = context["parallax"]
        # untrusted_context (a realized diff / task text) is forwarded to parallax's SEPARATE `context`
        # parameter, never concatenated into the claim — so injected instructions inside it cannot redirect
        # the verdict (audit: prompt-injection fix). Omitted when the caller supplies no untrusted span.
        untrusted = context.get("untrusted_context") or ""
        if untrusted:
            result = await client.verify(claim=context.get("claim", ""), context=untrusted)
        else:
            result = await client.verify(claim=context.get("claim", ""))
        evidence = {"tool": "parallax.verify", "output": result.output, "cost_usd": result.cost_usd}
        if parallax_passed(result):
            return VerifierOk(name=self.name, evidence=evidence)
        return VerifierFailed(name=self.name, reason="parallax.verify did not confirm the claim", evidence=evidence)


register_verifier("parallax_verify", ParallaxVerifyVerifier())
