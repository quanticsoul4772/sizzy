"""B3.2: full feature-class write loop on a synthetic existing repo — round-trip + rewind."""

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers feature_spec_claim)
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

CID = "corr-feature"
# the worktree "test suite": passes iff app.py declares foo() returning 42
_TEST_CMD = ["python", "-c", "import sys; sys.exit(0 if 'return 42' in open('app.py').read() else 1)"]
_QUALIFYING_DIFF = ("diff --git a/tests/test_foo.py b/tests/test_foo.py\n"
                    "+++ b/tests/test_foo.py\n+def test_foo():\n+    assert True\n")


def _existing_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "app.py").write_text("def foo():\n    return 0\n")  # the not-yet-implemented feature
    run("add", "-A")
    run("commit", "-m", "base")
    run("branch", "feature-base")
    return repo


class _Result:
    def __init__(self, passed):
        self.output = {"verified": passed}
        self.cost_usd = 0.0
        self.is_error = False


class _FakeParallax:
    def __init__(self, passed):
        self._passed = passed

    async def verify(self, claim, context=""):
        return _Result(self._passed)


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


def _make_complete_task(parallax_passed):
    lifecycle = TaskLifecycle()

    async def complete_task(planned_task, developer, conn, event_bus):
        tid, cid = planned_task.task_id, planned_task.correlation_id
        lifecycle.transition(tid, "queued", "running", event_bus, conn)
        ctx = {
            "task_id": tid, "correlation_id": cid, "test_command": _TEST_CMD, "cwd": developer.worktree.path,
            "parallax": _FakeParallax(parallax_passed), "spec_claim": planned_task.spec_claim,
            "diff_content": _QUALIFYING_DIFF,
        }
        result = await run_verifier(planned_task.verifier_ref, ctx, event_bus, conn,
                                    lifecycle=lifecycle, checkpoint=developer.checkpoint)
        if isinstance(result, VerifierOk):
            event_bus.emit_sync("reviewer_certified", {"task_id": tid, "reviewer_session_id": "rs", "evidence": {}, "correlation_id": cid, "certified_at_millis": 1}, correlation_id=cid)
            complete(tid, lifecycle, conn, event_bus)
        # on failure run_verifier already fired on_verifier_failure (rewind clean + reject -> terminal)

    return complete_task


def _run(tmp_path, *, feature_body, parallax_passed):
    repo = _existing_repo(tmp_path)
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
        editor.write_file("app.py", feature_body, predicted_success=0.9)

    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    tasks = [{"task_class": "feature", "description": "foo() returns 42", "scope_boundary": ["app.py"], "dependencies": []}]
    plan_id = asyncio.run(director.run(
        "spec-1", CID, tasks=tasks, developer_role_cls=DeveloperRole, complete_task=_make_complete_task(parallax_passed),
        developer_kwargs={"base_path": str(repo), "base_ref": "feature-base", "query_fn": _noop_query(), "write_hook": write_hook},
    ))
    return repo, conn, registry, plan_id


def test_feature_round_trip(tmp_path):
    repo, conn, registry, plan_id = _run(tmp_path, feature_body="def foo():\n    return 42\n", parallax_passed=True)
    task_id = f"{CID}-t0"

    # the feature verifier (test_suite + parallax) passed -> completed, earned twice
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)).fetchone()[0] == "pass"
    assert conn.execute("SELECT verdict FROM proj_reviewer_certs WHERE task_id=?", (task_id,)).fetchone()[0] == "certified"
    assert conn.execute("SELECT current_state, outcome FROM proj_task_lifecycle WHERE task_id=?", (task_id,)).fetchone() == ("completed", "completed")
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone()[0] == "completed"
    # write events carry the feature class for per-class Brier
    assert conn.execute("SELECT task_class FROM proj_developer_activity WHERE event_type='write_applied' AND task_id=?", (task_id,)).fetchone()[0] == "feature"
    assert verify_chain(conn) == conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert check_projection_rebuild_parity(conn, registry) is True


def test_feature_non_satisfying_rewinds_and_blocks(tmp_path):
    repo, conn, registry, plan_id = _run(tmp_path, feature_body="def foo():\n    return 41\n", parallax_passed=True)
    task_id = f"{CID}-t0"

    # test_suite axis fails (not 'return 42') -> verifier failed -> auto-rewind + reject
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)).fetchone()[0] == "fail"
    assert conn.execute("SELECT current_state FROM proj_task_lifecycle WHERE task_id=?", (task_id,)).fetchone()[0] == "rejected"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='rewind_performed'").fetchone()[0] == 1
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone()[0] == "blocked"
    assert check_projection_rebuild_parity(conn, registry) is True
