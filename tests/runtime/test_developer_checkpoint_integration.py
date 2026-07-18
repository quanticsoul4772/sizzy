"""B2.4: DeveloperRole.run() takes a baseline checkpoint; a manual rewind restores state."""

import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import PlannedTask
from devharness.checkpoint.rewind import rewind_to
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.worktree.isolate import Worktree, discard_worktree


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


def _task():
    return PlannedTask(
        task_id="t1", task_class="new_project_scaffold", description="d",
        scope_boundary=["**"], dependencies=[], correlation_id="c", verifier_ref="test_suite",
    )


def _noop_query():
    async def query(*, prompt, options):
        if False:
            yield None

    return query


def test_developer_takes_checkpoint_and_manual_rewind(tmp_path):
    repo = _git_repo(tmp_path)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)

    dev = DeveloperRole.spawn(
        conn=conn, correlation_id="c", event_bus=bus, base_path=str(repo), query_fn=_noop_query()
    )  # default worktree_factory + checkpoint_fn = real git
    asyncio.run(dev.run(_task(), "c"))

    assert dev.checkpoint is not None
    assert conn.execute("SELECT count(*) FROM proj_checkpoints").fetchone()[0] == 1

    worktree_path = dev.checkpoint.worktree_path
    readme = Path(worktree_path) / "README.md"
    readme.write_text("dirty\n")
    rewind_to(dev.checkpoint, bus, conn)
    assert readme.read_text() == "hi\n"  # restored to the developer's baseline checkpoint
    assert conn.execute("SELECT rewound_at_millis FROM proj_checkpoints").fetchone()[0] is not None

    discard_worktree(Worktree("t1", worktree_path, str(repo)))
