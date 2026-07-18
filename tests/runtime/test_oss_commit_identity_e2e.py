"""B4.5 e2e: an OSS commit lands under the bot identity (real git) + emits the event; non-OSS keeps
the default identity (B2.3 behavior)."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.checkpoint.base import take_checkpoint
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.oss.commit_identity import commit_with_identity, get_commit_identity
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.worktree.isolate import create_worktree, discard_worktree

REPO = "octo/widget"


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _upstream(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "operator@local")
    _git(repo, "config", "user.name", "operator")
    _git(repo, "checkout", "-q", "-b", "main")
    (repo / "README.md").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "release")
    return repo


def _bus():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_oss_commit_uses_bot_identity(tmp_path):
    repo = _upstream(tmp_path)
    conn, bus = _bus()
    wt = create_worktree("oss-c", str(repo), oss_task_id="oss-c", oss_target_branch="release")
    try:
        (Path(wt.path) / "feature.py").write_text("def f(): return 1\n")
        identity = get_commit_identity(REPO, "feature")
        sha = commit_with_identity(wt.path, "OSS contribution oss-c", identity,
                                   oss_task_id="oss-c", upstream_repo=REPO,
                                   event_bus=bus, correlation_id="c1", now_millis=lambda: 5)
        # the commit's author + committer are the OSS bot, not the operator
        assert _git(wt.path, "log", "-1", "--format=%an") == "devharness-oss-bot"
        assert _git(wt.path, "log", "-1", "--format=%ae") == "oss@devharness.local"
        assert _git(wt.path, "log", "-1", "--format=%cn") == "devharness-oss-bot"  # committer too
        # the event landed in proj_commit_identity with the right task/identity/sha
        row = conn.execute("SELECT oss_task_id, identity_name, commit_sha FROM proj_commit_identity").fetchone()
        assert row == ("oss-c", "devharness-oss-bot", sha)
        assert len(sha) == 40
    finally:
        discard_worktree(wt)
        _git(repo, "branch", "-D", "devharness-oss/oss-c")


def test_non_oss_commit_keeps_default_identity(tmp_path):
    repo = _upstream(tmp_path)
    _git(repo, "checkout", "-q", "main")
    conn, bus = _bus()
    wt = create_worktree("plain-c", str(repo))  # detached, non-OSS
    try:
        (Path(wt.path) / "x.py").write_text("y\n")
        take_checkpoint("plain-c", wt.path, "c2", bus, conn, now_millis=lambda: 5)
        # the checkpoint commit carries the operator identity configured on the repo, not the bot
        assert _git(wt.path, "log", "-1", "--format=%an") == "operator"
        assert conn.execute("SELECT count(*) FROM proj_commit_identity").fetchone()[0] == 0  # no OSS event
    finally:
        discard_worktree(wt)
