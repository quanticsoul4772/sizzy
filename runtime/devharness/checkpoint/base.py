"""Checkpoint mechanism (B2.4, §S4).

A per-task worktree checkpoint is a git commit of the worktree state. Taking one
emits checkpoint_taken; rewinding (rewind.py) resets the worktree to a checkpoint's
commit. Each task runs in a discardable worktree (B2.3) so a bad task reverts cleanly.
"""

import subprocess
import time
from uuid import uuid4

import msgspec

from devharness.events.registry import CheckpointTaken


class Checkpoint(msgspec.Struct, frozen=True, kw_only=True):
    checkpoint_id: str
    task_id: str
    worktree_path: str
    git_commit_sha: str
    correlation_id: str
    taken_at_millis: int
    schema_version: int = 1


def _git(worktree_path, *args) -> str:
    proc = subprocess.run(
        ["git", "-C", worktree_path, *args], check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


# Fallback commit identity, applied ONLY when the repo has no ``user.name``/``user.email`` configured —
# so a checkpoint commit never hits ``git commit`` exit 128 on a box without a global identity (which
# crashed the first VPS build, rev 0.3.86), WITHOUT overriding the operator's identity when they have
# one (that stays on the internal checkpoint commit).
_FALLBACK_IDENTITY = ("-c", "user.name=devharness-dev", "-c", "user.email=dev@devharness.local")


def _identity_fallback(worktree_path) -> tuple:
    """``_FALLBACK_IDENTITY`` if the repo configures no git identity, else ``()`` (use the operator's)."""
    for key in ("user.name", "user.email"):
        r = subprocess.run(["git", "-C", worktree_path, "config", key], capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return _FALLBACK_IDENTITY
    return ()


def take_checkpoint(task_id, worktree_path, correlation_id, event_bus, conn, *, now_millis=None) -> Checkpoint:
    """Stage + commit (allow-empty) the worktree, return the Checkpoint, emit checkpoint_taken."""
    _git(worktree_path, "add", "-A")
    _git(worktree_path, *_identity_fallback(worktree_path), "commit", "--allow-empty",
         "-m", f"devharness checkpoint {task_id}")
    sha = _git(worktree_path, "rev-parse", "HEAD")
    checkpoint_id = uuid4().hex
    taken_at = (now_millis or (lambda: int(time.time() * 1000)))()
    checkpoint = Checkpoint(
        checkpoint_id=checkpoint_id, task_id=task_id, worktree_path=worktree_path,
        git_commit_sha=sha, correlation_id=correlation_id, taken_at_millis=taken_at,
    )
    event_bus.emit_sync(
        "checkpoint_taken",
        msgspec.to_builtins(
            CheckpointTaken(
                task_id=task_id, checkpoint_id=checkpoint_id, ref=sha,
                worktree_path=worktree_path, git_commit_sha=sha, taken_at_millis=taken_at,
            )
        ),
        correlation_id=correlation_id,
    )
    return checkpoint
