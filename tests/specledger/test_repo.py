"""Tests for repo discovery."""

import pytest

from specledger.repo import RepoNotFound, find_repo_root


def test_finds_root_at_start(good_repo):
    assert find_repo_root(good_repo) == good_repo.resolve()


def test_finds_root_from_subdir(good_repo):
    subdir = good_repo / "runtime" / "devharness" / "events"
    assert find_repo_root(subdir) == good_repo.resolve()


def test_accepts_git_file_worktree(tmp_path, repo_builder):
    root = repo_builder(tmp_path)
    # Replace the .git dir marker with a .git file (git worktree shape).
    git_dir = root / ".git"
    import shutil

    shutil.rmtree(git_dir)
    (root / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n", encoding="utf-8")
    assert find_repo_root(root) == root.resolve()


def test_raises_when_no_repo(tmp_path):
    with pytest.raises(RepoNotFound):
        find_repo_root(tmp_path)


def test_raises_when_only_git_no_spec(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(RepoNotFound):
        find_repo_root(tmp_path)
