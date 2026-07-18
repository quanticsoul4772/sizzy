"""Worktree isolation (B2.3, §S4).

Each developer task runs in a discardable git worktree under a runtime-managed pool
outside the base repo. Isolation is not concurrency — the single-writer lock (Inv 1)
serializes worktrees; this module just buys clean rollback.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

POOL_DIRNAME = ".devharness-worktrees"
DEFAULT_OSS_BRANCH_PREFIX = "devharness-oss/"


@dataclass(frozen=True)
class Worktree:
    task_id: str
    path: str
    base_path: str
    fork_branch: str = ""  # B4.4: the OSS contribution branch (empty for non-OSS detached worktrees)


def _pool(base: Path) -> Path:
    # outside the repo tree: <repo-parent>/.devharness-worktrees/<repo-name>/
    return base.parent / POOL_DIRNAME / base.name


def oss_fork_branch(oss_task_id: str) -> str:
    """The OSS contribution branch name: <DEVHARNESS_OSS_BRANCH_PREFIX><oss_task_id> (local-only at B4.4)."""
    prefix = os.environ.get("DEVHARNESS_OSS_BRANCH_PREFIX", DEFAULT_OSS_BRANCH_PREFIX)
    return f"{prefix}{oss_task_id}"


def create_worktree(task_id: str, base_path: str, base_ref: str | None = None, *,
                    oss_task_id: str | None = None, oss_target_branch: str | None = None,
                    scratch_branch: str | None = None) -> Worktree:
    """`git worktree add` a fresh worktree for this task.

    base_ref=None (B2.3): fresh worktree at the repo's current HEAD (greenfield path).
    base_ref set (B3.1): worktree detached at that branch/commit in the existing repo, so the
    developer writes against real prior files.
    oss_task_id set (B4.4): a *fork-branch* worktree — a new branch ``devharness-oss/<oss_task_id>``
    is created off the upstream's ``oss_target_branch`` and checked out (not detached), so the OSS
    contribution lands on its own local branch. Changes never touch the base ref or the source tree.
    scratch_branch set (external-target write): a *named scratch branch* worktree — a new branch
    ``scratch_branch`` is created off ``base_ref`` (or HEAD) and checked out, so a non-OSS feature built
    into an external repo lands on its own branch (never that repo's main/working tree). Default None =
    the detached behavior (devharness-internal builds, discarded after the run).
    """
    base = Path(base_path).resolve()
    # Disable git's fsmonitor for this base repo (covers all its worktrees — they share config).
    # Git for Windows defaults core.fsmonitor=true, which spawns a detached `git fsmonitor--daemon`
    # per working tree. The per-task worktree churn orphans those daemons (they outlive
    # `git worktree remove`); under a multi-task drive they pile into the thousands, and the process
    # pressure trips the Agent SDK's 60s `initialize` timeout. fsmonitor's one-daemon-per-tree model is
    # incompatible with rapid create/destroy, so we turn it off here — idempotent, self-healing if the
    # config is reset, machine-independent. See CLAUDE.md (fsmonitor operational invariant).
    subprocess.run(["git", "-C", str(base), "config", "core.fsmonitor", "false"],
                   check=False, capture_output=True, text=True)
    pool = _pool(base)
    pool.mkdir(parents=True, exist_ok=True)
    wt_path = pool / task_id

    if oss_task_id is not None:
        fork_branch = oss_fork_branch(oss_task_id)
        cmd = ["git", "-C", str(base), "worktree", "add", "-b", fork_branch, str(wt_path)]
        if oss_target_branch is not None:
            cmd.append(oss_target_branch)  # branch off the upstream's target branch
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return Worktree(task_id=task_id, path=str(wt_path), base_path=str(base), fork_branch=fork_branch)

    if scratch_branch is not None:
        # non-OSS named-branch worktree (external target): the feature lands on its own branch, off
        # base_ref (or HEAD), never on the target repo's main or working tree.
        cmd = ["git", "-C", str(base), "worktree", "add", "-b", scratch_branch, str(wt_path)]
        if base_ref is not None:
            cmd.append(base_ref)
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return Worktree(task_id=task_id, path=str(wt_path), base_path=str(base), fork_branch=scratch_branch)

    cmd = ["git", "-C", str(base), "worktree", "add", "--detach", str(wt_path)]
    if base_ref is not None:
        cmd.append(base_ref)
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return Worktree(task_id=task_id, path=str(wt_path), base_path=str(base))


def discard_worktree(worktree: Worktree) -> None:
    """`git worktree remove --force` the worktree."""
    subprocess.run(
        ["git", "-C", worktree.base_path, "worktree", "remove", "--force", worktree.path],
        check=True, capture_output=True, text=True,
    )


def is_within_worktree(path: str, worktree: Worktree) -> bool:
    """True iff an absolute/relative target resolves inside the worktree root."""
    root = Path(worktree.path).resolve()
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    return target == root or root in target.parents
