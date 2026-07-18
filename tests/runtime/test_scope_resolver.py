"""Dispatch-time scope widening: the resolver returns only valid, existing, not-already-scoped files, and the
DeveloperRole UNIONS them onto scope_boundary so a write the model's scope missed is now allowed (was a
ScopeViolation). Widen-only — without the widener, behaviour is unchanged."""

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
from devharness.roles.scope_resolver import resolve_extra_scope

CID = "corr-widen"


class _Result:
    def __init__(self, text):
        self.total_cost_usd = 0.0
        self.result = text


def _query(text):
    async def q(*, prompt, options):
        yield _Result(text)
    return q


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
    return PlannedTask(task_id=f"{CID}-t0", task_class="new_project_scaffold", description="add a field to AppState",
                       scope_boundary=scope, dependencies=[], correlation_id=CID, spec_claim="")


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init"); run("config", "user.email", "t@t.t"); run("config", "user.name", "t")
    (repo / "README.md").write_text("hi\n")
    run("add", "-A"); run("commit", "-m", "init")
    return repo


# ---- resolver validation ----

def test_resolve_keeps_only_valid_existing_unscoped_paths(tmp_path):
    wt = tmp_path / "wt"
    (wt / "src").mkdir(parents=True)
    (wt / "src" / "state.rs").write_text("x")
    out = json.dumps(["src/state.rs", "src/nope.rs", "/abs/path.rs", "../escape.rs", "src/lib.rs"])
    res = asyncio.run(resolve_extra_scope(str(wt), _task(["src/lib.rs"]), query_fn=_query(out)))
    assert res == ["src/state.rs"]  # nonexistent / absolute / escape / already-scoped all dropped


def test_resolve_malformed_output_is_noop(tmp_path):
    wt = tmp_path / "wt"; wt.mkdir()
    assert asyncio.run(resolve_extra_scope(str(wt), _task(["x"]), query_fn=_query("not json at all"))) == []
    assert asyncio.run(resolve_extra_scope(str(wt), _task(["x"]), query_fn=_query("[]"))) == []


# ---- DeveloperRole union threading ----

def _run_with(tmp_path, scope, widener):
    repo = _git_repo(tmp_path)
    conn = sqlite3.connect(":memory:"); migrate(conn)
    bus = _bus(conn)

    def write_hook(editor, shell, test_runner):
        (Path(editor.worktree.path) / "widened.py").write_text("x\n")  # outside the model scope

    dev = DeveloperRole.spawn(conn=conn, correlation_id=CID, event_bus=bus, base_path=str(repo),
                              query_fn=_noop_query(), write_hook=write_hook, scope_widener=widener)
    asyncio.run(dev.run(_task(scope), CID))
    return dev


def test_widener_unions_extra_file_so_the_write_is_allowed(tmp_path):
    async def widener(worktree_path, planned_task):
        return ["widened.py"]
    dev = _run_with(tmp_path, ["allowed/**"], widener)
    assert dev._effective_scope == ["allowed/**", "widened.py"]
    assert dev.scope_violation is None
    assert (Path(dev.worktree.path) / "widened.py").exists()  # kept


def test_without_widener_same_write_is_a_violation(tmp_path):
    dev = _run_with(tmp_path, ["allowed/**"], None)
    assert dev.scope_violation == ["widened.py"]
    assert not (Path(dev.worktree.path) / "widened.py").exists()  # rewound
