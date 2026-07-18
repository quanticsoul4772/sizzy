"""B3.4: full refactor-class write loop on a synthetic existing repo with a mixed test suite."""

import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers refactor_behavior_preserving)
from devharness.events.bus import EventBus, verify_chain
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.roles.director import DirectorRole
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.task_lifecycle.done_is_earned import complete
from devharness.verifier.base import VerifierOk
from devharness.verifier.runner import run_verifier

CID = "corr-refactor"
# mixed suite: test_foo passes iff foo() == 42 (behaviour); test_bar is known-failing
_RUN_TESTS = (
    "import sys\nsys.path.insert(0, '.')\n"
    "try:\n    import app\n    foo_ok = app.foo() == 42\nexcept Exception:\n    foo_ok = False\n"
    "print('test_foo', 'pass' if foo_ok else 'fail')\nprint('test_bar', 'fail')\n"
)
PASS_FAIL = ["python", "-B", "run_tests.py"]


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "app.py").write_text("def foo():\n    return 42\n")
    (repo / "run_tests.py").write_text(_RUN_TESTS)
    run("add", "-A")
    run("commit", "-m", "base")
    run("branch", "refactor-base")
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
        ctx = {"task_id": tid, "correlation_id": cid, "cwd": developer.worktree.path,
               "checkpoint": developer.checkpoint, "pass_fail_command": PASS_FAIL}
        result = await run_verifier(planned_task.verifier_ref, ctx, event_bus, conn, lifecycle=lifecycle, checkpoint=developer.checkpoint)
        if isinstance(result, VerifierOk):
            event_bus.emit_sync("reviewer_certified", {"task_id": tid, "reviewer_session_id": "rs", "evidence": {}, "correlation_id": cid, "certified_at_millis": 1}, correlation_id=cid)
            complete(tid, lifecycle, conn, event_bus)

    return complete_task


def _run(tmp_path, refactor_body):
    repo = _repo(tmp_path)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    register_builtin_task_classes()
    conn.execute("INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) VALUES ('spec-1','spec',1,'{}',?,1,1)", (CID,))
    conn.commit()
    bus.emit_sync("spec_signed", {"spec_id": "spec-1", "signer": "operator", "signed_at_millis": 1}, correlation_id=CID)

    def write_hook(editor, shell, test_runner):
        editor.write_file("app.py", refactor_body, predicted_success=0.9)

    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    tasks = [{"task_class": "refactor", "description": "restructure foo", "scope_boundary": ["app.py"], "dependencies": []}]
    plan_id = asyncio.run(director.run(
        "spec-1", CID, tasks=tasks, developer_role_cls=DeveloperRole, complete_task=_make_complete_task(),
        developer_kwargs={"base_path": str(repo), "base_ref": "refactor-base", "query_fn": _noop_query(), "write_hook": write_hook},
    ))
    return conn, registry, plan_id


def test_refactor_behavior_preserving_round_trip(tmp_path):
    # restructured but foo() still returns 42 -> pass/fail set unchanged -> completed
    conn, registry, plan_id = _run(tmp_path, "def foo():\n    value = 42  # extracted\n    return value\n")
    task_id = f"{CID}-t0"
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)).fetchone()[0] == "pass"
    assert conn.execute("SELECT verdict FROM proj_reviewer_certs WHERE task_id=?", (task_id,)).fetchone()[0] == "certified"
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone()[0] == "completed"
    assert conn.execute("SELECT task_class FROM proj_developer_activity WHERE event_type='write_applied' AND task_id=?", (task_id,)).fetchone()[0] == "refactor"
    assert verify_chain(conn) == conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert check_projection_rebuild_parity(conn, registry) is True


def test_refactor_behavior_change_rewinds_and_blocks(tmp_path):
    # foo() now returns 99 -> test_foo flips pass->fail -> pass_to_fail -> rewind -> blocked
    conn, registry, plan_id = _run(tmp_path, "def foo():\n    return 99\n")
    task_id = f"{CID}-t0"
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)).fetchone()[0] == "fail"
    assert conn.execute("SELECT current_state FROM proj_task_lifecycle WHERE task_id=?", (task_id,)).fetchone()[0] == "rejected"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='rewind_performed'").fetchone()[0] == 1
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone()[0] == "blocked"
    assert check_projection_rebuild_parity(conn, registry) is True
