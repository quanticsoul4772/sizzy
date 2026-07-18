"""B4.5 ordering fix: a full OSS bugfix loop — the regression verifier's stash baseline works
because the fix is uncommitted at verify time; the bot-identity commit lands after it passes."""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401
from devharness.artifacts.plan import OssEnvelope, PlannedTask
from devharness.events.bus import EventBus
from devharness.lock.base import SingleWriterLock
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.verifier.base import VerifierOk
from devharness.verifier.runner import run_verifier

REPO = "octo/widget"
BUG_REGRESSION = ["python", "-B", "-c", "import sys; sys.exit(0 if 'return 42' in open('bug.py').read() else 1)"]
SUITE_OK = ["python", "-c", "import sys; sys.exit(0)"]


def _noop_query():
    async def q(*, prompt, options):
        if False:
            yield None
    return q


def test_oss_bugfix_e2e(tmp_path):
    import sqlite3
    repo = tmp_path / "upstream"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "operator@local")
    run("config", "user.name", "operator")
    run("checkout", "-b", "main")
    (repo / "bug.py").write_text("def foo():\n    return 0\n")  # the bug
    run("add", "-A")
    run("commit", "-m", "base")

    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    lifecycle = TaskLifecycle()

    task = PlannedTask(task_id="bf1", task_class="bugfix", description="foo returns 42", scope_boundary=["bug.py"],
                       dependencies=[], correlation_id="c", verifier_ref="bugfix_regression", is_oss=True,
                       oss_envelope=OssEnvelope(upstream_repo=REPO, license_spdx="MIT", requester_id="alice", target_branch="main"))

    async def oss_verify(planned_task, developer, conn, event_bus):
        lifecycle.transition(planned_task.task_id, "queued", "running", event_bus, conn)
        ctx = {"task_id": planned_task.task_id, "correlation_id": "c", "cwd": developer.worktree.path,
               "checkpoint": developer.checkpoint, "regression_command": BUG_REGRESSION, "test_command": SUITE_OK}
        return await run_verifier("bugfix_regression", ctx, event_bus, conn, lifecycle=lifecycle, checkpoint=developer.checkpoint)

    def write_hook(editor, shell, test_runner):
        editor.write_file("bug.py", "def foo():\n    return 42\n")  # the fix (uncommitted at verify time)

    dev = DeveloperRole(event_bus=bus, conn=conn, context={}, base_path=str(repo), lock=SingleWriterLock(),
                        write_hook=write_hook, oss_verify_fn=oss_verify, now_millis=lambda: 1, query_fn=_noop_query())
    asyncio.run(dev.run(task, "c"))

    # the bugfix verifier passed (baseline_should_fail saw return 0; post_should_pass saw return 42)
    assert isinstance(dev.oss_verify_result, VerifierOk)
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id='bf1'").fetchone()[0] == "pass"
    # the bot-identity commit landed after the verifier passed, on the fork branch
    assert conn.execute("SELECT count(*) FROM proj_commit_identity WHERE oss_task_id='bf1'").fetchone()[0] == 1
    head = subprocess.run(["git", "-C", dev.worktree.path, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert head == "devharness-oss/bf1"
