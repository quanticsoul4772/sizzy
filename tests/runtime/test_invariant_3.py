"""B1.4: Invariant 3 — director has no file tools and declares its own context
budget/sources with no silent inheritance from the research role."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.call_class import classify
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.mcp.parallax import ParallaxClient
from devharness.roles.director import DirectorRole
from devharness.roles.research import ResearchRole


def _client(cls):
    async def query(*, prompt, options):
        class _R:
            total_cost_usd = 0.0
            result = "ok"
            usage = {"input_tokens": 1, "output_tokens": 1}
            is_error = False

        yield _R()

    return cls(query_fn=query)


def test_director_has_no_file_tools():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    director = DirectorRole.spawn(conn=conn, correlation_id="d1", reasoning=_client(MCPReasoningClient), event_bus=EventBus(conn))
    inv = director.tool_inventory
    assert "Edit" not in inv and "Write" not in inv and "Bash" not in inv
    assert all(classify(tool) != "mutation" for tool in inv)


def test_director_declares_own_context_and_budget_no_inheritance():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    director = DirectorRole.spawn(conn=conn, correlation_id="d1", reasoning=_client(MCPReasoningClient), event_bus=bus)
    research = ResearchRole.spawn(conn=conn, correlation_id="r1", parallax=_client(ParallaxClient), event_bus=bus)

    # the director's context is assembled from its own correlation, not the research role's
    assert director.context["correlation_id"] == "d1"
    assert director.context is not research.context
    # a declared, positive reasoning (context) budget
    assert director.reasoning_budget_tokens > 0
