"""B2.7: Invariant 3 under dispatch — director has no write tools; its reasoning
budget accumulates from its own calls, not inherited from the developer's session."""

import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.call_class import classify
from devharness.events.bus import EventBus
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.director import DirectorRole, tool_inventory_for


class _R:
    total_cost_usd = 0.0
    result = "ok"
    usage = {"input_tokens": 5, "output_tokens": 5}  # 10 tokens per reasoning call
    is_error = False


def _reasoning():
    async def query(*, prompt, options):
        yield _R()

    return MCPReasoningClient(query_fn=query)


class _CostlyDeveloper:
    """A developer whose own cost must NOT bleed into the director's budget."""

    @classmethod
    def spawn(cls, *, conn, correlation_id, event_bus, **kwargs):
        return cls(conn, event_bus)

    def __init__(self, conn, event_bus):
        self.conn = conn
        self.event_bus = event_bus
        self.checkpoint = None
        self.total_cost_usd = 999.0  # large, separate from the director

    async def run(self, planned_task, correlation_id):
        self.event_bus.emit_sync(
            "task_started",
            {"task_id": planned_task.task_id, "role": "developer", "worktree_path": "/w", "correlation_id": correlation_id, "started_at_millis": 1},
            correlation_id=correlation_id,
        )


async def _complete(planned_task, developer, conn, event_bus):
    event_bus.emit_sync(
        "terminal_outcome",
        {"task_id": planned_task.task_id, "outcome": "completed", "detail": "", "reason": "", "correlation_id": planned_task.correlation_id, "terminated_at_millis": 9},
        correlation_id=planned_task.correlation_id,
    )


def test_director_no_write_tools():
    inv = tool_inventory_for(DirectorRole.ALLOWED_MCP_SERVERS)
    assert all(classify(tool) != "mutation" for tool in inv)
    assert hasattr(DirectorRole, "dispatch")  # dispatch is the only way it touches code


def test_director_budget_not_inherited_from_developer():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) "
        "VALUES ('spec-1', 'spec', 1, '{}', 'c', 1, 1)"
    )
    conn.commit()

    director = DirectorRole.spawn(conn=conn, correlation_id="c", reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    tasks = [{"task_class": "new_project_scaffold", "description": "d", "scope_boundary": ["src/**"], "dependencies": []}]
    asyncio.run(director.run("spec-1", "c", tasks=tasks, developer_role_cls=_CostlyDeveloper, complete_task=_complete))

    # the director made exactly 3 reasoning calls (fork + reflection + 1 per task) = 30 tokens,
    # and the developer's 999.0 cost did not bleed into the director's budget.
    assert director.reasoning_spent_tokens == 30
