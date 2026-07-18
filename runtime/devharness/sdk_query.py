"""Overage auth-fallback for the SDK message loops (rev 0.4.0).

The harness runs the Claude Agent SDK on the operator's claude.ai subscription (``ANTHROPIC_API_KEY`` is
popped at startup, so the CLI authenticates via the logged-in login). When a model's **weekly/overage
subscription quota is exhausted**, the CLI rejects the call and the SDK yields a structured
``RateLimitEvent`` (``rate_limit_info.status == "rejected"``) — or an ``AssistantMessage`` flagged
``billing_error`` — *before* it raises the exit-1 ``Exception``.

``run_query`` iterates the SDK message stream and, on THAT specific credit-exhaustion rejection **and only
then**, retries the same call **once** with the operator's valid API key injected via
``ClaudeAgentOptions.env`` (the API serves the model pay-as-you-go), so fable-5 — and any model — keeps
working when its included quota runs out. It is per-call, so the next call tries the subscription first
again and it **auto-reverts** when the weekly quota resets.

What it is NOT: not a model fallback (the requested model is unchanged); not error-hiding — the retry fires
only on the credit-exhaustion signal, every other error (including a transient ``five_hour`` cooldown)
re-raises unchanged, and the auth-switch is surfaced with a stderr line + the existing cost telemetry.
"""

import dataclasses
import json
import sys
from pathlib import Path

from claude_agent_sdk import AssistantMessage, RateLimitEvent, ToolUseBlock


def overage_key() -> str | None:
    """The API key to use for pay-as-you-go overage, sourced EXACTLY as the harness already sources the
    mcp-reasoning launch spec (``console/director.py:_reasoning_server_config``): the **top-level**
    ``~/.claude.json`` ``mcpServers["mcp-reasoning"]["env"]["ANTHROPIC_API_KEY"]``, falling back to
    ``["parallax"]``. Returns None if neither is present.

    Deliberately NOT a scan of all servers: the file also holds duplicate ``mcp-reasoning``/``parallax``
    blocks under ``projects.<path>.mcpServers`` with DIFFERENT keys; the top-level block is the one the
    harness already launches mcp-reasoning from, so it is the deterministic, consistent source.
    """
    path = Path.home() / ".claude.json"
    if not path.exists():
        return None
    servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
    for name in ("mcp-reasoning", "parallax"):
        key = (servers.get(name, {}).get("env") or {}).get("ANTHROPIC_API_KEY")
        if key:
            return key
    return None


def _is_credit_rejection(message) -> bool:
    """True iff ``message`` signals **weekly/overage credit exhaustion** — NOT a transient five_hour cooldown.

    Two channels (the CLI may use either): a ``RateLimitEvent`` whose overage is rejected or whose window is
    a seven_day/overage type (read the pass-through ``raw`` too, since the CLI emits type strings outside the
    SDK's ``Literal``), OR an ``AssistantMessage`` flagged ``billing_error``. A bare ``status=="rejected"``
    on a ``five_hour`` window is deliberately NOT a match — that is a short cooldown, not out-of-credits.
    """
    if isinstance(message, RateLimitEvent):
        info = message.rate_limit_info
        if info.status != "rejected":
            return False
        if info.overage_status == "rejected":
            return True
        window = f"{info.rate_limit_type or ''} {info.raw.get('rateLimitType', '')}"
        return "seven_day" in window or "overage" in window
    if isinstance(message, AssistantMessage):
        return message.error == "billing_error"
    return False


def _has_tool_use(messages) -> bool:
    """Any tool use in the buffered messages — a retry must not re-drive a model over a worktree the first
    attempt already wrote to (the developer path). Non-tool callers never trip this."""
    for m in messages:
        for block in getattr(m, "content", None) or []:
            if isinstance(block, ToolUseBlock):
                return True
    return False


async def run_query(query_fn, prompt, options):
    """Async-iterate ``query_fn(prompt=…, options=…)`` with the overage auth-fallback.

    Buffers the attempt. On a weekly/overage credit-exhaustion rejection with no prior tool use, retries
    ONCE with the valid API key injected into a copy of ``options`` and yields the retry's messages;
    otherwise yields the buffered attempt, re-raising any error unchanged. Yields the SDK ``Message``
    objects, so each call site's own per-message processing is untouched.
    """
    async def _attempt(opts):
        msgs, rejected, error = [], False, None
        try:
            async for message in query_fn(prompt=prompt, options=opts):
                if _is_credit_rejection(message):
                    rejected = True
                msgs.append(message)
        except BaseException as exc:  # noqa: BLE001 — classified by `rejected` below, else re-raised
            error = exc
        return msgs, rejected, error

    msgs, rejected, error = await _attempt(options)
    if rejected and not _has_tool_use(msgs):
        key = overage_key()
        if key:
            model = getattr(options, "model", None) or "?"
            sys.stderr.write(
                f"⚠ subscription quota exhausted for {model} — this call billed via the API key\n"
            )
            merged_env = {**(getattr(options, "env", None) or {}), "ANTHROPIC_API_KEY": key}
            msgs, _, error = await _attempt(dataclasses.replace(options, env=merged_env))
    if error is not None:
        raise error
    for m in msgs:
        yield m
