"""Realized-diff scope enforcement (rev 0.3.21).

Regression for finding #7: the live worker wrote a whole package via the ACI shell,
bypassing the per-write scope_gate and write tracking (0 editor write events). The
developer now enforces scope_boundary on the realized worktree diff after the worker
runs, regardless of write vector, and tracks in-scope non-editor writes.
"""

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import PlannedTask
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole

CID = "corr-scope"


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


def _noop_query():
    async def q(*, prompt, options):
        if False:
            yield None
    return q


def _bus(conn):
    reg = ProjectionRegistry()
    register_handlers(reg)
    return EventBus(conn, reg)


def _task(scope):
    return PlannedTask(
        task_id=f"{CID}-t0", task_class="new_project_scaffold", description="x",
        scope_boundary=scope, dependencies=[], correlation_id=CID,
    )


def _developer(conn, bus, repo, write_hook):
    return DeveloperRole.spawn(
        conn=conn, correlation_id=CID, event_bus=bus, base_path=str(repo),
        query_fn=_noop_query(), write_hook=write_hook,
    )


def test_out_of_scope_realized_write_is_rejected_and_rewound(tmp_path):
    repo = _git_repo(tmp_path)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = _bus(conn)

    def write_hook(editor, shell, test_runner):
        # a non-editor write (as the live worker did via the ACI shell): no write_applied event
        (Path(editor.worktree.path) / "escaped.py").write_text("x\n")

    dev = _developer(conn, bus, repo, write_hook)
    asyncio.run(dev.run(_task(["allowed/**"]), CID))

    assert dev.scope_violation == ["escaped.py"]
    assert not (Path(dev.worktree.path) / "escaped.py").exists()  # rewound clean


def test_in_scope_realized_write_is_tracked(tmp_path):
    repo = _git_repo(tmp_path)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = _bus(conn)

    def write_hook(editor, shell, test_runner):
        d = Path(editor.worktree.path) / "allowed"
        d.mkdir(parents=True, exist_ok=True)
        (d / "new.py").write_text("x\n")  # non-editor write, in scope

    dev = _developer(conn, bus, repo, write_hook)
    asyncio.run(dev.run(_task(["allowed/**"]), CID))

    assert dev.scope_violation is None
    writes = [json.loads(p) for (p,) in conn.execute("SELECT payload FROM events WHERE event_type='write_applied'")]
    assert any(r.get("action_kind") == "worktree_diff" and r.get("target_path") == "allowed/new.py" for r in writes)
    assert (Path(dev.worktree.path) / "allowed" / "new.py").exists()  # kept
