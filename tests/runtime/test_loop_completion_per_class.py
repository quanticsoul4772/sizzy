"""End-to-end completion guard for the sibling write-classes (bugfix / refactor / dependency_bump).

The feature class hid four stacked bugs behind green unit tests; these classes share the same
DeveloperRole + run_verifier + ReviewerRole path and had never run on a real path. The reviewer
previously forwarded only a few context fields, so it could not re-run the per-class verifiers
(bugfix_regression reads regression_command, refactor reads pass_fail_command, dependency_resolves
reads bump_command/manifest/lockfile) — KeyError, no certification. Each test below drives the real
developer acceptance AND the real ReviewerRole for its class through to `completed`; without the
reviewer forwarding the full verifier context, the reviewer half fails and the task never completes.
"""

import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers the per-class verifiers)
from devharness.events.bus import EventBus, verify_chain
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.roles.director import DirectorRole
from devharness.roles.reviewer import ReviewerRole
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.task_lifecycle.done_is_earned import complete, reject
from devharness.verifier.base import VerifierOk
from devharness.verifier.runner import run_verifier


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


def _repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    for rel, body in files.items():
        (repo / rel).write_text(body)
    run("add", "-A")
    run("commit", "-m", "base")
    run("branch", "task-base")
    return repo


def _make_complete_task(lifecycle, class_ctx):
    async def complete_task(planned_task, developer, conn, event_bus):
        tid, cid = planned_task.task_id, planned_task.correlation_id
        wt = developer.worktree
        lifecycle.transition(tid, "queued", "running", event_bus, conn)
        vctx = {
            "task_id": tid, "correlation_id": cid, "cwd": wt.path, "parallax": None,
            "spec_claim": planned_task.spec_claim or planned_task.description,
            "claim": planned_task.spec_claim or planned_task.description,
            "checkpoint": developer.checkpoint,
            **class_ctx,
        }
        result = await run_verifier(planned_task.verifier_ref, vctx, event_bus, conn,
                                    lifecycle=lifecycle, checkpoint=developer.checkpoint)
        if not isinstance(result, VerifierOk):
            return
        reviewer = ReviewerRole(parallax=None, event_bus=event_bus, conn=conn,
                                context=dict(vctx, prior_events=[]), fresh_context=True,
                                verifiers=[planned_task.verifier_ref])
        certified = await reviewer.run(tid, "spec-1", "plan-1", cid)
        if certified:
            complete(tid, lifecycle, conn, event_bus)
        else:
            reject(tid, "reviewer rejected", lifecycle, conn, event_bus)

    return complete_task


def _run(tmp_path, cid, *, files, task_class, scope, write, class_ctx):
    repo = _repo(tmp_path, files)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    register_builtin_task_classes()
    conn.execute("INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) VALUES ('spec-1','spec',1,'{}',?,1,1)", (cid,))
    conn.commit()
    bus.emit_sync("spec_signed", {"spec_id": "spec-1", "signer": "operator", "signed_at_millis": 1}, correlation_id=cid)

    director = DirectorRole.spawn(conn=conn, correlation_id=cid, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    tasks = [{"task_class": task_class, "description": f"{task_class} task", "scope_boundary": scope, "dependencies": []}]
    plan_id = asyncio.run(director.run(
        "spec-1", cid, tasks=tasks, developer_role_cls=DeveloperRole,
        complete_task=_make_complete_task(TaskLifecycle(), class_ctx),
        developer_kwargs={"base_path": str(repo), "base_ref": "task-base", "query_fn": _noop_query(), "write_hook": write},
    ))
    return conn, registry, plan_id


def _assert_completed(conn, registry, plan_id, cid):
    task_id = f"{cid}-t0"
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)).fetchone()[0] == "pass"
    assert conn.execute("SELECT verdict FROM proj_reviewer_certs WHERE task_id=?", (task_id,)).fetchone()[0] == "certified"
    assert conn.execute("SELECT current_state, outcome FROM proj_task_lifecycle WHERE task_id=?", (task_id,)).fetchone() == ("completed", "completed")
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone()[0] == "completed"
    assert verify_chain(conn) == conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert check_projection_rebuild_parity(conn, registry) is True


_HAS_42 = ["python", "-c", "import sys; sys.exit(0 if 'return 42' in open('app.py').read() else 1)"]


def test_bugfix_completes_end_to_end(tmp_path):
    # regression test fails at baseline (return 0) and passes after the fix (return 42); suite passes
    def write(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)

    conn, registry, plan_id = _run(
        tmp_path, "corr-bugfix", files={"app.py": "def foo():\n    return 0\n"},
        task_class="bugfix", scope=["app.py"], write=write,
        class_ctx={"regression_command": _HAS_42, "test_command": _HAS_42},
    )
    _assert_completed(conn, registry, plan_id, "corr-bugfix")


def test_refactor_completes_end_to_end(tmp_path):
    # behaviour-preserving: the pass/fail set is identical pre/post (constant pass_fail_command)
    def write(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():  # refactored\n    return 0\n", predicted_success=0.9)

    conn, registry, plan_id = _run(
        tmp_path, "corr-refactor", files={"app.py": "def foo():\n    return 0\n"},
        task_class="refactor", scope=["app.py"], write=write,
        class_ctx={"pass_fail_command": ["python", "-c", "print('t1 pass')"], "test_command": ["python", "-c", "pass"]},
    )
    _assert_completed(conn, registry, plan_id, "corr-refactor")


def test_dependency_bump_completes_end_to_end(tmp_path):
    # the worker writes the bumped manifest + lockfile; the bump command is a no-op that exits 0
    def write(editor, shell, test_runner):
        editor.write_file("requirements.txt", "foo==2.0\n", predicted_success=0.9)
        editor.write_file("requirements.lock", "foo==2.0\n", predicted_success=0.9)

    conn, registry, plan_id = _run(
        tmp_path, "corr-dep", files={"requirements.txt": "foo==1.0\n", "requirements.lock": "foo==1.0\n"},
        task_class="dependency_bump", scope=["requirements.txt", "requirements.lock"], write=write,
        class_ctx={
            "dependency_name": "foo", "target_version": "2.0", "bump_command": ["python", "-c", "pass"],
            "manifest_path": "requirements.txt", "lockfile_path": "requirements.lock",
            "test_command": ["python", "-c", "pass"],
        },
    )
    _assert_completed(conn, registry, plan_id, "corr-dep")
