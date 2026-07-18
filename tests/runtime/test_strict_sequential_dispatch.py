"""B3.0: strict-sequential multi-task dispatch — one task in flight, dependency-ordered,
all-done -> completed, any-rejected -> blocked."""

import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.director import DirectorRole

CID = "corr-seq"


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
        self.event_bus.emit_sync(
            "task_started",
            {"task_id": planned_task.task_id, "role": "developer", "worktree_path": "/w", "correlation_id": correlation_id, "started_at_millis": 1},
            correlation_id=correlation_id,
        )


def _completer(order, reject_task_id=None):
    async def complete_task(planned_task, developer, conn, event_bus):
        order.append(planned_task.task_id)
        outcome = "rejected" if planned_task.task_id == reject_task_id else "completed"
        event_bus.emit_sync(
            "terminal_outcome",
            {"task_id": planned_task.task_id, "outcome": outcome, "detail": "", "reason": "bad" if outcome == "rejected" else "",
             "correlation_id": planned_task.correlation_id, "terminated_at_millis": 9},
            correlation_id=planned_task.correlation_id,
        )
    return complete_task


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    conn.execute("INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) VALUES ('spec-1', 'spec', 1, '{}', ?, 1, 1)", (CID,))
    conn.commit()
    return conn, registry, bus


# t0 <- t1 <- t2 (linear dependency chain)
_TASKS = [
    {"task_class": "new_project_scaffold", "description": "a", "scope_boundary": ["**"], "dependencies": []},
    {"task_class": "new_project_scaffold", "description": "b", "scope_boundary": ["**"], "dependencies": [f"{CID}-t0"]},
    {"task_class": "new_project_scaffold", "description": "c", "scope_boundary": ["**"], "dependencies": [f"{CID}-t1"]},
]


def test_all_complete_marks_plan_completed():
    conn, _registry, bus = _setup()
    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    order = []
    plan_id = asyncio.run(director.run("spec-1", CID, tasks=_TASKS, developer_role_cls=_FakeDeveloper, complete_task=_completer(order)))

    assert order == [f"{CID}-t0", f"{CID}-t1", f"{CID}-t2"]  # dependency order, one at a time
    assert conn.execute("SELECT current_state, current_task_id FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone() == ("completed", None)
    states = dict(conn.execute("SELECT task_id, task_state FROM proj_plan_tasks WHERE plan_id=?", (plan_id,)).fetchall())
    assert states == {f"{CID}-t0": "completed", f"{CID}-t1": "completed", f"{CID}-t2": "completed"}


def test_rejection_blocks_and_stops_dispatch():
    conn, _registry, bus = _setup()
    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    order = []
    plan_id = asyncio.run(director.run("spec-1", CID, tasks=_TASKS, developer_role_cls=_FakeDeveloper, complete_task=_completer(order, reject_task_id=f"{CID}-t1")))

    assert order == [f"{CID}-t0", f"{CID}-t1"]  # t2 never dispatched after t1 rejected
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone()[0] == "blocked"
    assert conn.execute("SELECT task_state FROM proj_plan_tasks WHERE task_id=?", (f"{CID}-t1",)).fetchone()[0] == "rejected"
    assert conn.execute("SELECT count(*) FROM proj_plan_tasks WHERE task_id=?", (f"{CID}-t2",)).fetchone()[0] == 0
