"""B2.10: rewind path — verifier failure triggers a clean rewind + reject + plan blocked."""

import asyncio
import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.checkpoint.base import take_checkpoint
from devharness.events.bus import EventBus
from devharness.events.registry import TerminalOutcome
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.integration import integrate
from devharness.task_lifecycle.auto_rewind import on_verifier_failure
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.verifier.base import Verifier, VerifierFailed
from devharness.verifier.registry import FALSIFIERS, register_verifier
from devharness.verifier.runner import run_verifier
from devharness.worktree.isolate import create_worktree, discard_worktree


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


class _AlwaysFail(Verifier):
    name = "_b210_fail"

    async def verify(self, context):
        return VerifierFailed(name=self.name, reason="tests failed")


def test_rewind_path_restores_and_blocks(tmp_path):
    repo = _git_repo(tmp_path)
    worktree = create_worktree("t1", str(repo))
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    cid = "corr-rewind"

    # the task is dispatched + started (so proj_plan + lifecycle exist)
    bus.emit_sync("plan_drafted", {"plan_id": "p1", "spec_id": "s", "task_count": 1}, correlation_id=cid)
    bus.emit_sync("task_dispatched", {"plan_id": "p1", "task_id": "t1", "dispatched_to_role": "developer", "dispatched_by_role": "director", "correlation_id": cid, "dispatched_at_millis": 1}, correlation_id=cid)
    bus.emit_sync("task_started", {"task_id": "t1", "role": "developer", "worktree_path": worktree.path, "correlation_id": cid, "started_at_millis": 2}, correlation_id=cid)

    lifecycle = TaskLifecycle()
    lifecycle.transition("t1", "queued", "running", bus, conn)
    checkpoint = take_checkpoint("t1", worktree.path, cid, bus, conn)  # baseline state of the worktree

    # capture the actual checkpoint bytes (robust to git's line-ending handling)
    readme = Path(worktree.path) / "README.md"
    scratch = Path(worktree.path) / "scratch.txt"
    baseline_readme = hashlib.sha256(readme.read_bytes()).hexdigest()

    # the developer makes a tracked change + an untracked file
    readme.write_text("dirtied\n")
    scratch.write_text("untracked\n")

    if "_b210_fail" not in FALSIFIERS:
        register_verifier("_b210_fail", _AlwaysFail())

    # verifier fails -> auto-rewind (clean) + reject
    result = asyncio.run(run_verifier("_b210_fail", {"task_id": "t1", "correlation_id": cid}, bus, conn, lifecycle=lifecycle, checkpoint=checkpoint))
    assert isinstance(result, VerifierFailed)

    # worktree fully clean: tracked restored, untracked removed
    assert hashlib.sha256(readme.read_bytes()).hexdigest() == baseline_readme
    assert not scratch.exists()

    # task rejected; rewind recorded
    assert lifecycle.state("t1") == "rejected"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='rewind_performed'").fetchone()[0] == 1
    assert conn.execute("SELECT rewound_at_millis FROM proj_checkpoints WHERE checkpoint_id=?", (checkpoint.checkpoint_id,)).fetchone()[0] is not None

    # integrate the rejected terminal -> plan blocked
    terminal = TerminalOutcome(task_id="t1", outcome="rejected", detail="verifier_failed", reason="verifier_failed", correlation_id=cid, terminated_at_millis=9)
    assert integrate("p1", "t1", terminal, conn, bus) == "blocked"
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id='p1'").fetchone()[0] == "blocked"

    discard_worktree(worktree)
