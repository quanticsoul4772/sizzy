"""B2.10 cut-line acceptance: the full write loop research -> sign -> plan -> dispatch
-> write -> verify -> certify -> terminal -> integrate, end to end."""

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import msgspec

from devharness import boot
from devharness.artifacts.spec import Assumption, SpecArtifact
from devharness.cli.answer import answer_question
from devharness.cli.sign import sign_spec
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

CID = "corr-b2-accept"


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
        tid, cid = planned_task.task_id, planned_task.correlation_id
        lifecycle.transition(tid, "queued", "running", event_bus, conn)
        event_bus.emit_sync("verifier_outcome", {"task_id": tid, "verifier": "test_suite", "passed": True, "detail": "", "evidence": {"n": 11}}, correlation_id=cid)
        # stand-in for the fresh-context ReviewerRole verdict (ReviewerRole itself is B2.5-tested)
        event_bus.emit_sync("reviewer_certified", {"task_id": tid, "reviewer_session_id": "rs", "evidence": {}, "correlation_id": cid, "certified_at_millis": 1}, correlation_id=cid)
        complete(tid, lifecycle, conn, event_bus)

    return complete_task


def test_b2_full_write_loop(tmp_path):
    repo = _git_repo(tmp_path)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)

    # --- research: 2 Q/A cycles + 1 assumption + a persisted, drafted spec ---
    bus.emit_sync("research_started", {"research_id": CID, "topic": "scaffold a project"}, correlation_id=CID)
    for i, (q, a) in enumerate([("scope?", "all"), ("non-goals?", "none")]):
        qid = f"{CID}-q{i}"
        bus.emit_sync("question_asked", {"research_id": CID, "question_id": qid, "question_text": q}, correlation_id=CID)
        answer_question(conn, bus, qid, a, now_millis=lambda: 1)
    bus.emit_sync("assumption_flagged", {"research_id": CID, "text": "single operator", "confidence": 0.9, "low_confidence_flag": False}, correlation_id=CID)

    spec_id = "spec-b2"
    spec = SpecArtifact(problem="scaffold", scope="greenfield", non_goals=[], interfaces=[], success_criteria=["signed"], verification_plan="tests", assumptions=[Assumption(text="single operator", confidence=0.9, low_confidence_flag=False)], correlation_id=CID)
    conn.execute("INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, ?, ?, 1, 0)", (spec_id, json.dumps(msgspec.to_builtins(spec)), CID))
    conn.commit()
    bus.emit_sync("spec_drafted", {"spec_id": spec_id, "title": "scaffold"}, correlation_id=CID)

    # --- sign (real CLI) ---
    sign_spec(conn, bus, spec_id, operator="operator", now_millis=lambda: 1)
    assert conn.execute("SELECT signed FROM artifacts WHERE artifact_id=?", (spec_id,)).fetchone()[0] == 1

    # --- plan -> dispatch -> write -> verify -> certify -> terminal -> integrate ---
    def write_hook(editor, shell, test_runner):
        editor.write_file("src/scaffold.py", "# scaffold\n", predicted_success=0.9)

    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    tasks = [{"task_class": "new_project_scaffold", "description": "scaffold", "scope_boundary": ["**"], "dependencies": []}]
    plan_id = asyncio.run(director.run(
        spec_id, CID, tasks=tasks, developer_role_cls=DeveloperRole, complete_task=_make_complete_task(),
        developer_kwargs={"base_path": str(repo), "query_fn": _noop_query(), "write_hook": write_hook},
    ))

    # --- every loop event fired ---
    types = {row[0] for row in conn.execute("SELECT DISTINCT event_type FROM events")}
    for et in ("research_started", "question_asked", "question_answered", "assumption_flagged", "spec_drafted",
               "spec_signed", "director_decision", "plan_drafted", "task_dispatched", "write_lock_acquired",
               "task_started", "checkpoint_taken", "write_attempted", "write_applied", "verifier_outcome",
               "reviewer_certified", "terminal_outcome", "write_lock_released"):
        assert et in types, et

    # --- Inv 7 + Inv 9: valid hash chain + full correlation coverage ---
    assert verify_chain(conn) == conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert all(r[0] for r in conn.execute("SELECT correlation_id FROM events"))

    # --- Inv 10: exactly one terminal for the task ---
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 1

    # --- every B2 projection updated ---
    task_id = f"{CID}-t0"
    assert conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 0  # released
    assert conn.execute("SELECT count(*) FROM proj_task_started WHERE task_id=?", (task_id,)).fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM proj_checkpoints WHERE task_id=?", (task_id,)).fetchone()[0] == 1
    activity = {r[0] for r in conn.execute("SELECT event_type FROM proj_developer_activity WHERE task_id=?", (task_id,))}
    assert {"task_dispatched", "task_started", "write_attempted", "write_applied"} <= activity
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)).fetchone()[0] == "pass"
    assert conn.execute("SELECT verdict FROM proj_reviewer_certs WHERE task_id=?", (task_id,)).fetchone()[0] == "certified"
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone()[0] == "completed"
    assert conn.execute("SELECT count(*) FROM proj_task_dispatched WHERE task_id=?", (task_id,)).fetchone()[0] == 1
    assert conn.execute("SELECT current_state, outcome FROM proj_task_lifecycle WHERE task_id=?", (task_id,)).fetchone() == ("completed", "completed")

    # --- Inv 8: parity over all 23 projections; 24-name boot check passes ---
    assert check_projection_rebuild_parity(conn, registry) is True
    assert boot.check_required_gates_registered() is True
    assert len(boot.registered_check_names()) == len(boot.REQUIRED_GATES)
    assert boot.check_terminal_outcome_required_per_task(conn) is True
