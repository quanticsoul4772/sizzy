"""External-target build (Gap A/B).

The developer can build into a SEPARATE repo: it lands the feature on a named scratch branch, never
touching that repo's main, and leaves the realized diff non-empty after run() — committing is the driver's
post-certification job, not run()'s (committing inside run() would empty `git diff HEAD` and starve the
verifier). Devharness-internal builds (scratch_branch=None) keep the detached/no-commit path.
"""

import asyncio
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

CID = "corr-ext"


def _git_repo(tmp_path):
    repo = tmp_path / "target"
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
        task_id=f"{CID}-t0", task_class="feature", description="add a thing",
        scope_boundary=scope, dependencies=[], correlation_id=CID,
    )


def test_scratch_branch_build_isolates_external_repo_main(tmp_path):
    repo = _git_repo(tmp_path)
    head_before = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout.strip()
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = _bus(conn)

    def write_hook(editor, shell, test_runner):
        d = Path(editor.worktree.path) / "feat"
        d.mkdir(parents=True, exist_ok=True)
        (d / "new.py").write_text("x = 1\n")

    dev = DeveloperRole.spawn(
        conn=conn, correlation_id=CID, event_bus=bus, base_path=str(repo),
        scratch_branch="devharness/ext-feat", query_fn=_noop_query(), write_hook=write_hook,
    )
    asyncio.run(dev.run(_task(["feat/**"]), CID))

    # in scope, and the worktree is on the named scratch branch (not detached)
    assert dev.scope_violation is None
    branch = subprocess.run(["git", "-C", dev.worktree.path, "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    assert branch == "devharness/ext-feat"
    assert dev.worktree.fork_branch == "devharness/ext-feat"

    # the realized diff is NON-EMPTY after run() — run() must NOT commit (commit is the driver's post-cert
    # job). If run() committed, `git diff HEAD` would be empty and feature_spec_claim would have nothing to verify.
    diff = dev._realized_diff(dev.worktree)
    assert "feat/new.py" in diff and "x = 1" in diff

    # the external repo's main/HEAD is untouched — the feature never reached it
    head_after = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
    assert head_after == head_before


def test_internal_build_stays_detached_and_uncommitted(tmp_path):
    """Back-compat: scratch_branch=None (devharness-internal) keeps the detached worktree, no branch."""
    repo = _git_repo(tmp_path)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = _bus(conn)

    def write_hook(editor, shell, test_runner):
        (Path(editor.worktree.path) / "a.py").write_text("y = 2\n")

    dev = DeveloperRole.spawn(
        conn=conn, correlation_id=CID, event_bus=bus, base_path=str(repo),
        query_fn=_noop_query(), write_hook=write_hook,
    )
    asyncio.run(dev.run(_task(["**"]), CID))

    assert dev.worktree.fork_branch == ""
    branch = subprocess.run(["git", "-C", dev.worktree.path, "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    assert branch == "HEAD"  # detached
