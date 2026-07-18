"""B1.4: DirectorRole — read-only, refuses unsigned spec, plans + persists."""

import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.call_class import classify
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.roles.director import DirectorRole


class _R:
    def __init__(self, usage):
        self.total_cost_usd = 0.0
        self.result = "ok"
        self.usage = usage
        self.is_error = False


def _reasoning(usage=None):
    usage = usage or {"input_tokens": 10, "output_tokens": 5}

    async def query(*, prompt, options):
        yield _R(usage)

    return MCPReasoningClient(query_fn=query)


def _insert_spec(conn, artifact_id, correlation_id, signed):
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, '{}', ?, 1, ?)",
        (artifact_id, correlation_id, signed),
    )
    conn.commit()


def test_allowed_servers_and_no_write_tools():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    director = DirectorRole.spawn(conn=conn, correlation_id="corr-1", reasoning=_reasoning(), event_bus=EventBus(conn))
    assert director.allowed_mcp_servers == ["mcp-reasoning", "parallax"]
    inv = director.tool_inventory
    assert "Edit" not in inv and "Write" not in inv and "Bash" not in inv
    assert all(classify(tool) != "mutation" for tool in inv)


def test_refuses_unsigned_spec():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    _insert_spec(conn, "spec-1", "corr-1", signed=0)
    director = DirectorRole.spawn(conn=conn, correlation_id="corr-1", reasoning=_reasoning(), event_bus=bus)

    result = asyncio.run(director.run("spec-1", "corr-1"))
    assert result is None
    kinds = [
        __import__("json").loads(p[0])["decision_kind"]
        for p in conn.execute("SELECT payload FROM events WHERE event_type='director_decision'")
    ]
    assert "abort" in kinds
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='plan_drafted'").fetchone()[0] == 0


def test_plans_signed_spec_and_persists():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    _insert_spec(conn, "spec-1", "corr-1", signed=1)
    director = DirectorRole.spawn(
        conn=conn, correlation_id="corr-1", reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 9
    )

    plan_id = asyncio.run(director.run("spec-1", "corr-1"))

    order = [row[0] for row in conn.execute("SELECT event_type FROM events ORDER BY seq")]
    assert order.index("director_decision") < order.index("plan_drafted")
    row = conn.execute("SELECT artifact_type FROM artifacts WHERE artifact_id = ?", (plan_id,)).fetchone()
    assert row == ("plan",)
