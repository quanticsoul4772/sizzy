"""B2.7: the full read+write loop closes end-to-end (sign -> plan -> dispatch ->
write -> verify -> certify -> terminal=completed -> integrate)."""

import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.events.bus import EventBus, verify_chain
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.roles.director import DirectorRole
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.task_lifecycle.done_is_earned import complete


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "README.md").write_text("hi\n")
    run("add", "-A")
    run("commit", "-m", "init")
    return repo


class _R:
    total_cost_usd = 0.0
    result = "ok"
    usage = {"input_tokens": 1, "output_tokens": 1}
    is_error = False


def _reasoning():
    async def query(*, prompt, options):
        yield _R()

    return MCPReasoningClient(query_fn=query)


def _noop_query():
    async def query(*, prompt, options):
        if False:
            yield None

    return query


def _make_complete_task():
    lifecycle = TaskLifecycle()

    async def complete_task(planned_task, developer, conn, event_bus):
        tid = planned_task.task_id
        cid = planned_task.correlation_id
        lifecycle.transition(tid, "queued", "running", event_bus, conn)  # sync in-process state
        event_bus.emit_sync("verifier_outcome", {"task_id": tid, "verifier": "test_suite", "passed": True, "detail": "", "evidence": {}}, correlation_id=cid)
        event_bus.emit_sync("reviewer_certified", {"task_id": tid, "reviewer_session_id": "s", "evidence": {}, "correlation_id": cid, "certified_at_millis": 1}, correlation_id=cid)
        complete(tid, lifecycle, conn, event_bus)  # done-is-earned -> terminal completed

    return complete_task


def test_full_loop_closes(tmp_path):
    repo = _git_repo(tmp_path)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    cid = "corr-e2e"

    # research-flow stand-in: a signed spec lands in the artifacts table + event log
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) "
        "VALUES ('spec-1', 'spec', 1, '{}', ?, 1, 1)", (cid,)
    )
    conn.commit()
    bus.emit_sync("spec_signed", {"spec_id": "spec-1", "signer": "operator", "signed_at_millis": 1}, correlation_id=cid)

    director = DirectorRole.spawn(conn=conn, correlation_id=cid, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    tasks = [{"task_class": "new_project_scaffold", "description": "scaffold", "scope_boundary": ["**"], "dependencies": []}]

    plan_id = asyncio.run(director.run(
        "spec-1", cid, tasks=tasks,
        developer_role_cls=DeveloperRole, complete_task=_make_complete_task(),
        developer_kwargs={"base_path": str(repo), "query_fn": _noop_query()},
    ))

    types = {row[0] for row in conn.execute("SELECT DISTINCT event_type FROM events")}
    # the whole loop fired
    for et in ("spec_signed", "plan_drafted", "task_dispatched", "task_started", "write_lock_acquired",
               "write_lock_released", "checkpoint_taken", "verifier_outcome", "reviewer_certified", "terminal_outcome"):
        assert et in types, et

    # lock released, plan completed, one terminal, no silent termination
    assert conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 0
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id = ?", (plan_id,)).fetchone()[0] == "completed"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 1
    assert conn.execute("SELECT outcome FROM proj_task_lifecycle WHERE task_id = ?", (f"{cid}-t0",)).fetchone()[0] == "completed"
    assert boot.check_terminal_outcome_required_per_task(conn) is True

    # spine integrity: valid hash chain + projection parity over the whole loop
    assert verify_chain(conn) == conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert check_projection_rebuild_parity(conn, registry) is True
