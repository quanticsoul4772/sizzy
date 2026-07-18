"""B3.5: full dependency_bump write loop on a synthetic existing repo (offline-deterministic)."""

import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers dependency_resolves)
from devharness.artifacts.plan import PlannedTask
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

CID = "corr-bump"
# offline-deterministic stand-ins (no network): the "bump" trivially succeeds; the suite checks app.py
BUMP_OK = ["python", "-c", "import sys; sys.exit(0)"]
SUITE = ["python", "-B", "-c", "import sys; sys.exit(0 if 'return 42' in open('app.py').read() else 1)"]


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "pyproject.toml").write_text('[project]\ndependencies = ["requests==2.30.0"]\n')
    (repo / "requirements.lock").write_text("requests==2.30.0\n")
    (repo / "app.py").write_text("def foo():\n    return 42\n")
    run("add", "-A")
    run("commit", "-m", "base")
    run("branch", "bump-base")
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
        ctx = {"task_id": tid, "correlation_id": cid, "cwd": developer.worktree.path, "checkpoint": developer.checkpoint,
               "bump_command": BUMP_OK, "test_command": SUITE,
               "dependency_name": planned_task.dependency_name, "target_version": planned_task.target_version,
               "manifest_path": planned_task.manifest_path, "lockfile_path": planned_task.lockfile_path}
        result = await run_verifier(planned_task.verifier_ref, ctx, event_bus, conn, lifecycle=lifecycle, checkpoint=developer.checkpoint)
        if isinstance(result, VerifierOk):
            event_bus.emit_sync("reviewer_certified", {"task_id": tid, "reviewer_session_id": "rs", "evidence": {}, "correlation_id": cid, "certified_at_millis": 1}, correlation_id=cid)
            complete(tid, lifecycle, conn, event_bus)

    return complete_task


def _run(tmp_path, app_body):
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

    # the developer applies the bump (manifest + lockfile to target) and any code change
    def write_hook(editor, shell, test_runner):
        editor.write_file("pyproject.toml", '[project]\ndependencies = ["requests==2.31.0"]\n')
        editor.write_file("requirements.lock", "requests==2.31.0\n")
        editor.write_file("app.py", app_body)

    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    tasks = [{
        "task_class": "dependency_bump", "description": "bump requests to 2.31.0",
        "scope_boundary": ["pyproject.toml", "requirements.lock", "app.py"], "dependencies": [],
        "dependency_name": "requests", "target_version": "2.31.0",
        "bump_command": "pip install requests==2.31.0", "manifest_path": "pyproject.toml", "lockfile_path": "requirements.lock",
    }]
    plan_id = asyncio.run(director.run(
        "spec-1", CID, tasks=tasks, developer_role_cls=DeveloperRole, complete_task=_make_complete_task(),
        developer_kwargs={"base_path": str(repo), "base_ref": "bump-base", "query_fn": _noop_query(), "write_hook": write_hook},
    ))
    return conn, registry, plan_id


def test_dependency_bump_round_trip(tmp_path):
    conn, registry, plan_id = _run(tmp_path, "def foo():\n    return 42\n")  # bump applies, suite still green
    task_id = f"{CID}-t0"
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)).fetchone()[0] == "pass"
    assert conn.execute("SELECT verdict FROM proj_reviewer_certs WHERE task_id=?", (task_id,)).fetchone()[0] == "certified"
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone()[0] == "completed"
    assert conn.execute("SELECT task_class FROM proj_developer_activity WHERE event_type='write_applied' AND task_id=? LIMIT 1", (task_id,)).fetchone()[0] == "dependency_bump"
    assert verify_chain(conn) == conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert check_projection_rebuild_parity(conn, registry) is True


def test_dependency_bump_breaking_change_rewinds_and_blocks(tmp_path):
    conn, registry, plan_id = _run(tmp_path, "def foo():\n    return 0\n")  # bump applied but the suite breaks
    task_id = f"{CID}-t0"
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)).fetchone()[0] == "fail"
    assert conn.execute("SELECT current_state FROM proj_task_lifecycle WHERE task_id=?", (task_id,)).fetchone()[0] == "rejected"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='rewind_performed'").fetchone()[0] == 1
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone()[0] == "blocked"
    assert check_projection_rebuild_parity(conn, registry) is True


class _FakeDeveloper:
    @classmethod
    def spawn(cls, *, conn, correlation_id, event_bus, **kwargs):
        return cls(conn, event_bus)

    def __init__(self, conn, event_bus):
        self.conn = conn
        self.event_bus = event_bus
        self.checkpoint = None

    async def run(self, planned_task, correlation_id):
        raise AssertionError("developer must not run when admission denies")


async def _unused_complete(planned_task, developer, conn, event_bus):
    raise AssertionError("complete_task must not run when admission denies")


def test_over_wide_bump_denied_at_blast_radius(tmp_path):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    register_builtin_task_classes()
    bus.emit_sync("plan_drafted", {"plan_id": "p1", "spec_id": "s", "task_count": 1}, correlation_id=CID)
    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    # 201 declared paths exceeds dependency_bump's blast_radius_limit of 200
    wide_scope = [f"f{i}.py" for i in range(201)]
    task = PlannedTask(task_id="t1", task_class="dependency_bump", description="d", scope_boundary=wide_scope,
                       dependencies=[], correlation_id=CID, verifier_ref="dependency_resolves")
    terminal = asyncio.run(director.dispatch(task, _FakeDeveloper, conn, bus, plan_id="p1", complete_task=_unused_complete))
    assert terminal.outcome == "aborted"
    denied = [r[0] for r in conn.execute("SELECT json_extract(payload,'$.gate') FROM events WHERE event_type='gate_fired' AND json_extract(payload,'$.decision')='deny'")]
    assert "blast_radius_gate" in denied
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id='p1'").fetchone()[0] == "blocked"
