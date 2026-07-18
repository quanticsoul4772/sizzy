"""B3.1: create_worktree(base_ref=...) builds an isolated worktree off an existing branch."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.worktree.isolate import create_worktree, discard_worktree


def _repo_with_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "app.py").write_text("v = 1\n")
    run("add", "-A")
    run("commit", "-m", "init")
    run("branch", "feature-base")
    # advance main so HEAD differs from feature-base
    (repo / "app.py").write_text("v = 2\n")
    run("add", "-A")
    run("commit", "-m", "advance main")
    return repo


def test_worktree_starts_from_base_ref(tmp_path):
    repo = _repo_with_branch(tmp_path)
    wt = create_worktree("t1", str(repo), base_ref="feature-base")
    try:
        # the worktree reflects feature-base (v = 1), not main HEAD (v = 2)
        assert (Path(wt.path) / "app.py").read_text() == "v = 1\n"
    finally:
        discard_worktree(wt)


def test_worktree_changes_do_not_touch_source(tmp_path):
    repo = _repo_with_branch(tmp_path)
    wt = create_worktree("t2", str(repo), base_ref="feature-base")
    try:
        (Path(wt.path) / "app.py").write_text("dirtied in worktree\n")
        (Path(wt.path) / "new.py").write_text("x\n")
        # the source repo working tree and the base ref are untouched
        assert (repo / "app.py").read_text() == "v = 2\n"
        assert not (repo / "new.py").exists()
    finally:
        discard_worktree(wt)


def test_discard_removes_worktree(tmp_path):
    repo = _repo_with_branch(tmp_path)
    wt = create_worktree("t3", str(repo), base_ref="feature-base")
    assert Path(wt.path).exists()
    discard_worktree(wt)
    assert not Path(wt.path).exists()


def test_base_ref_none_preserves_greenfield_at_head(tmp_path):
    repo = _repo_with_branch(tmp_path)
    wt = create_worktree("t4", str(repo))  # no base_ref -> HEAD (main, v = 2)
    try:
        assert (Path(wt.path) / "app.py").read_text() == "v = 2\n"
    finally:
        discard_worktree(wt)
