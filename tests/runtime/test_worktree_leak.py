"""Resource-leak guards for the worktree pool (regression for the jqlite-drive leaks).

The harness creates a git worktree per task. Two leaks bit a multi-task drive:
  - **fsmonitor**: Git for Windows defaults core.fsmonitor=true, spawning a detached
    `git fsmonitor--daemon` per working tree. The per-task worktree churn orphaned them (they outlive
    `git worktree remove`); ~1,400 piled up and the process pressure tripped the Agent SDK's 60s
    `initialize` timeout. create_worktree now disables core.fsmonitor on the base repo.
  - **worktree registrations**: create/discard must not leak `git worktree list` entries.

Deterministic (config + registry assertions, not process counts) so it runs reliably in CI.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.worktree.isolate import create_worktree, discard_worktree


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "core.fsmonitor", "true")  # simulate the Git-for-Windows system default
    (repo / "f.txt").write_text("x")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def test_create_worktree_disables_fsmonitor(tmp_path):
    repo = _init_repo(tmp_path)
    assert _git(repo, "config", "--get", "core.fsmonitor").strip() == "true"
    create_worktree("t0", str(repo))
    # turned off so the churning worktrees never spawn a fsmonitor--daemon to orphan
    assert _git(repo, "config", "--get", "core.fsmonitor").strip() == "false"


def test_worktree_pool_does_not_leak_registrations(tmp_path):
    repo = _init_repo(tmp_path)
    baseline = len(_git(repo, "worktree", "list").splitlines())
    for i in range(5):
        wt = create_worktree(f"t{i}", str(repo))
        discard_worktree(wt)
    _git(repo, "worktree", "prune")
    after = len(_git(repo, "worktree", "list").splitlines())
    assert after == baseline, f"worktree registrations leaked across create/discard cycles: {baseline} -> {after}"
