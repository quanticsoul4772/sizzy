"""Overage auth-fallback (`sdk_query.run_query`, rev 0.4.0): on a weekly/overage credit-exhaustion
rejection — and only then — retry the SAME call once with the API key injected; everything else surfaces.
Injected fake `query_fn`, no live SDK.
"""

import asyncio
import sys
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
    ToolUseBlock,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import sdk_query


def _rle(**info):
    return RateLimitEvent(rate_limit_info=RateLimitInfo(**info), uuid="u", session_id="s")


CREDIT = _rle(status="rejected", overage_status="rejected", rate_limit_type="overage")
FIVE_HOUR = _rle(status="rejected", rate_limit_type="five_hour")
BILLING = AssistantMessage(content=[], model="claude-fable-5", error="billing_error")
TOOL_USE = AssistantMessage(content=[ToolUseBlock(id="t", name="Edit", input={})], model="m")


def _result(cost=0.01, text="done"):
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                         num_turns=1, session_id="s", total_cost_usd=cost, result=text)


def _query_fn(attempts):
    """attempts: list of (messages, exc_or_None) per attempt. Records the options each call received."""
    calls = []

    def q(*, prompt, options):
        idx = len(calls)
        calls.append(options)
        msgs, exc = attempts[idx]

        async def gen():
            for m in msgs:
                yield m
            if exc is not None:
                raise exc
        return gen()
    return q, calls


def _run(query_fn, options=None):
    options = options or ClaudeAgentOptions(setting_sources=[], model="claude-fable-5")
    out = []

    async def go():
        async for m in sdk_query.run_query(query_fn, "hi", options):
            out.append(m)
    err = None
    try:
        asyncio.run(go())
    except BaseException as e:  # noqa: BLE001
        err = e
    return out, err


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(sdk_query, "overage_key", lambda: "test-key")


def test_credit_rejection_retries_on_the_key(capsys):
    q, calls = _query_fn([
        ([CREDIT], RuntimeError("Command failed with exit code 1")),  # attempt 1: rejected then raise
        ([_result(text="retried-ok")], None),                          # attempt 2: on the key
    ])
    out, err = _run(q)
    assert err is None
    assert len(calls) == 2
    assert calls[0].env == {}                                   # first attempt: subscription, no key
    assert calls[1].env["ANTHROPIC_API_KEY"] == "test-key"      # retry: key injected
    assert [type(m).__name__ for m in out] == ["ResultMessage"] # caller sees ONLY the retry
    assert out[0].result == "retried-ok"
    assert "billed via the API key" in capsys.readouterr().err  # visible


def test_billing_error_assistant_message_also_triggers():
    q, calls = _query_fn([([BILLING], RuntimeError("exit 1")), ([_result()], None)])
    out, err = _run(q)
    assert err is None and len(calls) == 2 and calls[1].env["ANTHROPIC_API_KEY"] == "test-key"


def test_five_hour_cooldown_does_not_retry():
    boom = RuntimeError("Command failed with exit code 1")
    q, calls = _query_fn([([FIVE_HOUR], boom)])
    out, err = _run(q)
    assert err is boom and len(calls) == 1        # transient — surfaces, no key switch


def test_success_flushes_unchanged_no_key():
    q, calls = _query_fn([([_result(text="fine")], None)])
    out, err = _run(q)
    assert err is None and len(calls) == 1
    assert out[0].result == "fine" and calls[0].env == {}


def test_non_ratelimit_error_reraises_unchanged():
    boom = RuntimeError("some other failure")
    q, calls = _query_fn([([], boom)])
    out, err = _run(q)
    assert err is boom and len(calls) == 1


def test_rejection_with_no_key_surfaces(monkeypatch):
    monkeypatch.setattr(sdk_query, "overage_key", lambda: None)
    boom = RuntimeError("Command failed with exit code 1")
    q, calls = _query_fn([([CREDIT], boom)])
    out, err = _run(q)
    assert err is boom and len(calls) == 1        # no key -> surface, never swallowed


def test_rejection_without_a_raise_is_still_retried():
    # F5: a rejection that ends WITHOUT raising must still retry (else a spurious "no ResultMessage")
    q, calls = _query_fn([([CREDIT, _result(text="stale")], None), ([_result(text="retried")], None)])
    out, err = _run(q)
    assert err is None and len(calls) == 2
    assert [m.result for m in out if hasattr(m, "result")] == ["retried"]


def test_tool_use_before_rejection_does_not_retry():
    # F11: a mid-session rejection (after ACI writes) must surface, not re-drive over a dirtied worktree
    boom = RuntimeError("Command failed with exit code 1")
    q, calls = _query_fn([([TOOL_USE, CREDIT], boom)])
    out, err = _run(q)
    assert err is boom and len(calls) == 1
