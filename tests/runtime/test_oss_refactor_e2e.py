"""B4.5 ordering fix: a full OSS refactor loop — the behavior-preserving verifier compares the
per-test pass/fail set baseline vs post against the uncommitted tree; commit lands after it passes."""

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
REFACTOR_PASSFAIL = ["python", "-B", "run_tests.py"]
_RUN_TESTS = (
    "import sys\nsys.path.insert(0, '.')\n"
    "try:\n    import refac\n    ok = refac.value() == 7\nexcept Exception:\n    ok = False\n"
    "print('test_value', 'pass' if ok else 'fail')\nprint('test_known_fail', 'fail')\n"
)


def _noop_query():
    async def q(*, prompt, options):
        if False:
            yield None
    return q


def test_oss_refactor_e2e(tmp_path):
    import sqlite3
    repo = tmp_path / "upstream"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "operator@local")
    run("config", "user.name", "operator")
    run("checkout", "-b", "main")
    (repo / "refac.py").write_text("def value():\n    return 7\n")
    (repo / "run_tests.py").write_text(_RUN_TESTS)
    run("add", "-A")
    run("commit", "-m", "base")

    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    lifecycle = TaskLifecycle()

    task = PlannedTask(task_id="rf1", task_class="refactor", description="restructure value()", scope_boundary=["refac.py"],
                       dependencies=[], correlation_id="c", verifier_ref="refactor_behavior_preserving", is_oss=True,
                       oss_envelope=OssEnvelope(upstream_repo=REPO, license_spdx="MIT", requester_id="alice", target_branch="main"))

    async def oss_verify(planned_task, developer, conn, event_bus):
        lifecycle.transition(planned_task.task_id, "queued", "running", event_bus, conn)
        ctx = {"task_id": planned_task.task_id, "correlation_id": "c", "cwd": developer.worktree.path,
               "checkpoint": developer.checkpoint, "pass_fail_command": REFACTOR_PASSFAIL}
        return await run_verifier("refactor_behavior_preserving", ctx, event_bus, conn, lifecycle=lifecycle, checkpoint=developer.checkpoint)

    def write_hook(editor, shell, test_runner):
        # behavior-preserving refactor: value() still returns 7
        editor.write_file("refac.py", "def value():\n    result = 7  # refactored\n    return result\n")

    dev = DeveloperRole(event_bus=bus, conn=conn, context={}, base_path=str(repo), lock=SingleWriterLock(),
                        write_hook=write_hook, oss_verify_fn=oss_verify, now_millis=lambda: 1, query_fn=_noop_query())
    asyncio.run(dev.run(task, "c"))

    # the pass/fail set is unchanged baseline vs post -> VerifierOk
    assert isinstance(dev.oss_verify_result, VerifierOk)
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id='rf1'").fetchone()[0] == "pass"
    assert conn.execute("SELECT count(*) FROM proj_commit_identity WHERE oss_task_id='rf1'").fetchone()[0] == 1
