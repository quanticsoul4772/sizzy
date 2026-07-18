"""Rewind mechanism (B2.4, §S4).

On verifier failure, rewind the worktree to the last good checkpoint's commit. The
automatic verifier-failure trigger wires in B2.5/B2.6; B2.4 ships the primitive.
"""

import subprocess
import time

import msgspec

from devharness.events.registry import RewindPerformed


def rewind_to(checkpoint, event_bus, conn, *, clean=False, now_millis=None) -> int:
    """git reset --hard to the checkpoint commit; emit rewind_performed; return rewound_at_millis.

    clean=True also runs `git clean -fd` to remove untracked files (full revert, B2.6).
    """
    subprocess.run(
        ["git", "-C", checkpoint.worktree_path, "reset", "--hard", checkpoint.git_commit_sha],
        check=True, capture_output=True, text=True,
    )
    if clean:
        subprocess.run(
            ["git", "-C", checkpoint.worktree_path, "clean", "-fd"],
            check=True, capture_output=True, text=True,
        )
    rewound_at = (now_millis or (lambda: int(time.time() * 1000)))()
    event_bus.emit_sync(
        "rewind_performed",
        msgspec.to_builtins(
            RewindPerformed(
                checkpoint_id=checkpoint.checkpoint_id, task_id=checkpoint.task_id,
                worktree_path=checkpoint.worktree_path, git_commit_sha=checkpoint.git_commit_sha,
                correlation_id=checkpoint.correlation_id, rewound_at_millis=rewound_at,
            )
        ),
        correlation_id=checkpoint.correlation_id,
    )
    return rewound_at
