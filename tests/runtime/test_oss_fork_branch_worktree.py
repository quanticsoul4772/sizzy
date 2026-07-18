"""B4.4: create_worktree(oss_task_id=...) makes a devharness-oss/<id> branch off target_branch."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.worktree.isolate import create_worktree, discard_worktree, oss_fork_branch


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-b", "main")
    (repo / "README.md").write_text("upstream\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "release")  # the OSS target branch
    (repo / "rel.txt").write_text("on release\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "release commit")
    _git(repo, "checkout", "-q", "main")
    return repo


def test_fork_branch_off_target(tmp_path):
    repo = _repo(tmp_path)
    wt = create_worktree("oss-1", str(repo), oss_task_id="oss-1", oss_target_branch="release")
    try:
        assert wt.fork_branch == "devharness-oss/oss-1"
        # the worktree HEAD is on the fork branch...
        head = subprocess.run(["git", "-C", wt.path, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
        assert head == "devharness-oss/oss-1"
        # ...and it branched off release (rel.txt present, from the release commit)
        assert (Path(wt.path) / "rel.txt").exists()
    finally:
        discard_worktree(wt)
        _git(repo, "branch", "-D", "devharness-oss/oss-1")


def test_non_oss_preserves_detached_behavior(tmp_path):
    repo = _repo(tmp_path)
    wt = create_worktree("plain-1", str(repo))
    try:
        assert wt.fork_branch == ""
        head = subprocess.run(["git", "-C", wt.path, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
        assert head == "HEAD"  # detached
    finally:
        discard_worktree(wt)


def test_configurable_prefix(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_BRANCH_PREFIX", "contrib/")
    assert oss_fork_branch("xyz") == "contrib/xyz"
