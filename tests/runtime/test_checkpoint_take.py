"""B2.4: take_checkpoint creates a git snapshot commit + emits checkpoint_taken."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.checkpoint.base import take_checkpoint
from devharness.events.bus import EventBus
from devharness.migrate import migrate
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


def test_take_checkpoint_commits_and_emits(tmp_path):
    repo = _git_repo(tmp_path)
    worktree = create_worktree("t1", str(repo))
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)

    checkpoint = take_checkpoint("t1", worktree.path, "c", bus, conn, now_millis=lambda: 5)
    assert checkpoint.task_id == "t1"
    head = subprocess.run(["git", "-C", worktree.path, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert checkpoint.git_commit_sha == head

    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='checkpoint_taken'").fetchone()[0])
    assert payload["worktree_path"] == worktree.path
    assert payload["git_commit_sha"] == checkpoint.git_commit_sha
    assert payload["taken_at_millis"] == 5
    discard_worktree(worktree)


def test_checkpoint_commits_without_a_configured_git_identity(tmp_path, monkeypatch):
    """A box with NO git identity configured must not break the checkpoint commit — it falls back to an
    inline identity (rev 0.3.86; `git commit` exit 128 crashed the first VPS build). When one IS
    configured, the operator's identity is kept (test_non_oss_commit_keeps_default_identity)."""
    empty = tmp_path / "empty_gitconfig"
    empty.write_text("")  # suppress global + system config so git finds NO identity anywhere
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(empty))
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    (repo / "README.md").write_text("hi\n")
    run("add", "-A")
    run("-c", "user.name=seed", "-c", "user.email=s@s", "commit", "-m", "init")  # setup only (no config)
    worktree = create_worktree("t2", str(repo))
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    take_checkpoint("t2", worktree.path, "c", bus, conn, now_millis=lambda: 5)  # must NOT raise (exit 128)
    author = subprocess.run(
        ["git", "-C", worktree.path, "log", "-1", "--format=%an <%ae>"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert author == "devharness-dev <dev@devharness.local>"  # the fallback identity was applied
    discard_worktree(worktree)
