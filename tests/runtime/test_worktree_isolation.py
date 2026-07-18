"""B2.3: worktree create/discard via git; out-of-worktree writes refused."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.aci.editor import EditorActions, ScopeViolation
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.worktree.isolate import create_worktree, discard_worktree, is_within_worktree


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *args: subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "README.md").write_text("hi\n")
    run("add", "-A")
    run("commit", "-m", "init")
    return repo


def test_create_and_discard(tmp_path):
    repo = _git_repo(tmp_path)
    worktree = create_worktree("task-1", str(repo))
    assert Path(worktree.path).is_dir()
    listing = subprocess.run(["git", "-C", str(repo), "worktree", "list"], capture_output=True, text=True).stdout
    assert "task-1" in listing

    discard_worktree(worktree)
    assert not Path(worktree.path).exists()


def test_is_within_worktree(tmp_path):
    repo = _git_repo(tmp_path)
    worktree = create_worktree("task-2", str(repo))
    assert is_within_worktree("src/main.py", worktree)
    assert not is_within_worktree("../../escape.txt", worktree)
    discard_worktree(worktree)


def test_default_worktree_is_detached(tmp_path):
    """Back-compat: with no scratch_branch the worktree is detached (devharness-internal builds)."""
    repo = _git_repo(tmp_path)
    worktree = create_worktree("task-det", str(repo))
    assert worktree.fork_branch == ""
    branch = subprocess.run(["git", "-C", worktree.path, "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    assert branch == "HEAD"  # detached HEAD
    discard_worktree(worktree)


def test_scratch_branch_worktree_isolates_from_main(tmp_path):
    """Gap B: a scratch_branch worktree lands commits on its own branch; the source repo's main is untouched."""
    repo = _git_repo(tmp_path)
    head_before = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout.strip()
    worktree = create_worktree("task-sb", str(repo), scratch_branch="devharness/feat-x")
    assert worktree.fork_branch == "devharness/feat-x"
    # checked out on the named branch, not detached
    branch = subprocess.run(["git", "-C", worktree.path, "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    assert branch == "devharness/feat-x"
    # a commit in the worktree lands on the scratch branch
    (Path(worktree.path) / "feature.py").write_text("x = 1\n")
    run_wt = lambda *a: subprocess.run(["git", "-C", worktree.path, *a], check=True, capture_output=True, text=True)
    run_wt("add", "-A")
    run_wt("-c", "user.email=d@d.d", "-c", "user.name=d", "commit", "-m", "feat")
    # the source repo's main/HEAD is unchanged — the feature never touched it
    head_after = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
    assert head_after == head_before
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline", "devharness/feat-x"],
                         capture_output=True, text=True).stdout
    assert "feat" in log
    discard_worktree(worktree)
    # the branch persists after the worktree is removed (the operator can review it)
    branches = subprocess.run(["git", "-C", str(repo), "branch", "--list", "devharness/feat-x"],
                              capture_output=True, text=True).stdout
    assert "devharness/feat-x" in branches


def test_out_of_worktree_write_refused(tmp_path):
    repo = _git_repo(tmp_path)
    worktree = create_worktree("task-3", str(repo))
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    editor = EditorActions(
        worktree=worktree, scope_boundary=["**"], event_bus=EventBus(conn), conn=conn, correlation_id="c", task_id="task-3"
    )
    # writes within the worktree are allowed even with a permissive scope
    editor.write_file("src/main.py", "x = 1\n")
    assert (Path(worktree.path) / "src" / "main.py").exists()
    # escaping the worktree is refused
    with pytest.raises(ScopeViolation):
        editor.write_file("../../escape.txt", "nope")
    discard_worktree(worktree)
