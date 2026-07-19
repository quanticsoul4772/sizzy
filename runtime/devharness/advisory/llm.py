"""Advisory-lite's own LLM call (rev 0.4.26).

One module-level ``_complete`` the handlers (and the unit tests, via monkeypatch) share. It calls the
Agent SDK directly — NOT ``devharness.sdk_query.run_query`` — for two reasons: the substitute server
must stay free of the relay/overage machinery (a quota rejection surfaces as a tool error and the
harness fails closed, which is correct), and ``run_query`` writes to stderr/stdout paths this process
must keep clean (stdout IS the MCP protocol). The SDK is lazy-imported: the ``.complete()`` relay
sessions boot this server even when no tool is called, so import cost is startup cost.

Env posture (design-review settled): do NOT pop ``ANTHROPIC_API_KEY`` here. The drivers already pop
it at startup, so it is absent from the inheritance chain EXCEPT (a) during a rev-0.4.0 overage
retry, where the relay deliberately injects it so this nested call bills the key exactly when the
subscription is exhausted, and (b) when the user's launch-spec ``env`` sets it deliberately.

Model: ``DEVHARNESS_ADVISORY_MODEL``, else the T1 advisory model computed with the process-wide
``DEVHARNESS_MODEL`` pin EXCLUDED — an operator pinning the writer family would otherwise silently
collapse the verifier-family independence that is advisory-lite's one recoverable independence axis.
"""

import os


def _advisory_model() -> str:
    """The judge model for advisory calls (see module docstring for the pin-exclusion rationale)."""
    explicit = os.environ.get("DEVHARNESS_ADVISORY_MODEL")
    if explicit:
        return explicit
    from devharness.models import model_for_tier

    pin = os.environ.pop("DEVHARNESS_MODEL", None)
    try:
        return model_for_tier("T1")
    finally:
        if pin is not None:
            os.environ["DEVHARNESS_MODEL"] = pin


async def _complete(prompt: str, *, model: str | None = None) -> str:
    """One plain completion (no tools, no MCP servers, ``setting_sources=[]`` — the commitment-3
    posture adopted voluntarily; this server is neither an AgentRole nor an MCPClient, so the boot
    check does not bind it, but the spirit does). Raises RuntimeError on an errored or missing
    result — a raise becomes an MCP tool error the harness fails closed on."""
    import claude_agent_sdk as sdk  # lazy: server boot must stay light (the .complete() relay boots us)

    options = sdk.ClaudeAgentOptions(
        setting_sources=[],
        mcp_servers={},
        allowed_tools=[],
        max_turns=1,
        model=model or _advisory_model(),
    )
    result = None
    async for message in sdk.query(prompt=prompt, options=options):
        if hasattr(message, "total_cost_usd"):
            result = message
    if result is None:
        raise RuntimeError("advisory completion produced no result")
    if getattr(result, "is_error", False):
        raise RuntimeError("advisory completion errored")
    return str(getattr(result, "result", "") or "")
