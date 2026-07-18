"""B1.0: parallax + mcp_reasoning wrappers instantiate, declare setting_sources=[],
and surface per-call cost. The Agent SDK ``query`` is injected (no live server)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.mcp.parallax import ParallaxClient


class _FakeResult:
    def __init__(self, cost):
        self.total_cost_usd = cost
        self.usage = {"input_tokens": 10, "output_tokens": 5}
        self.result = "ok"
        self.is_error = False


def _fake_query(cost):
    async def query(*, prompt, options):
        # the posture must flow through to the SDK options
        assert options.setting_sources == []
        yield _FakeResult(cost)

    return query


def test_parallax_instantiates_with_empty_setting_sources():
    client = ParallaxClient(query_fn=_fake_query(0.0))
    assert client.setting_sources == []
    assert client.options().setting_sources == []
    assert "decide" in client.tools and "research" in client.tools
    assert client.allowed_tools[0].startswith("mcp__parallax__")


def test_parallax_surfaces_per_call_cost():
    client = ParallaxClient(query_fn=_fake_query(0.0123))
    result = asyncio.run(client.decide(decision="ship or not", options=["ship", "hold"]))
    assert result.cost_usd == 0.0123
    assert client.last_cost_usd == 0.0123
    assert client.total_cost_usd == 0.0123
    # a second call accumulates
    asyncio.run(client.verify(claim="x"))
    assert client.total_cost_usd == 0.0246


def test_mcp_reasoning_instantiates_and_costs():
    client = MCPReasoningClient(query_fn=_fake_query(0.5))
    assert client.setting_sources == []
    assert client.tools == ["reasoning_decision", "reasoning_reflection", "reasoning_meta"]
    result = asyncio.run(client.reasoning_decision(question="fork or sequence?"))
    assert result.cost_usd == 0.5
    assert result.usage == {"input_tokens": 10, "output_tokens": 5}
