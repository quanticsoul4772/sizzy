"""B2.7: DirectorRole.dispatch emits task_dispatched, runs developer, awaits terminal."""

import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import PlannedTask
from devharness.events.bus import EventBus
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.director import DirectorRole


class _R:
    total_cost_usd = 0.0
    result = "ok"
    usage = {"input_tokens": 1, "output_tokens": 1}
    is_error = False


def _reasoning():
    async def query(*, prompt, options):
        yield _R()

    return MCPReasoningClient(query_fn=query)


class _FakeDeveloper:
    @classmethod
    def spawn(cls, *, conn, correlation_id, event_bus, **kwargs):
        return cls(conn, event_bus)

    def __init__(self, conn, event_bus):
        self.conn = conn
        self.event_bus = event_bus
        self.checkpoint = None

    async def run(self, planned_task, correlation_id):
        # the developer starts the task (lifecycle -> running via the handler)
        self.event_bus.emit_sync(
            "task_started",
            {"task_id": planned_task.task_id, "role": "developer", "worktree_path": "/w", "correlation_id": correlation_id, "started_at_millis": 1},
            correlation_id=correlation_id,
        )


async def _complete_task(planned_task, developer, conn, event_bus):
    # stand-in inner loop: emit a completed terminal_outcome
    event_bus.emit_sync(
        "terminal_outcome",
        {"task_id": planned_task.task_id, "outcome": "completed", "detail": "", "reason": "", "correlation_id": planned_task.correlation_id, "terminated_at_millis": 9},
        correlation_id=planned_task.correlation_id,
    )


def test_dispatch_emits_runs_and_returns_terminal():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    bus.emit_sync("plan_drafted", {"plan_id": "p1", "spec_id": "s", "task_count": 1}, correlation_id="c")

    director = DirectorRole.spawn(conn=conn, correlation_id="c", reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 3)
    task = PlannedTask(task_id="t1", task_class="new_project_scaffold", description="d", scope_boundary=["src/**"], dependencies=[], correlation_id="c", verifier_ref="test_suite")

    terminal = asyncio.run(director.dispatch(task, _FakeDeveloper, conn, bus, plan_id="p1", complete_task=_complete_task))

    assert terminal.outcome == "completed"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='task_dispatched'").fetchone()[0] == 1
    row = conn.execute("SELECT dispatched_to_role, dispatched_by_role FROM proj_task_dispatched WHERE task_id='t1'").fetchone()
    assert row == ("developer", "director")
    # plan advanced to executing then completed
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id='p1'").fetchone()[0] == "completed"
