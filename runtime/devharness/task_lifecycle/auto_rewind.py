"""Verifier-failure auto-rewind (B2.6, §S4).

On a verifier failure, rewind the worktree to the last good checkpoint (clean) and
reject the task. Wired into the B2.2 run_verifier path.
"""

from devharness.checkpoint.rewind import rewind_to
from devharness.task_lifecycle.done_is_earned import reject


def on_verifier_failure(task_id, lifecycle, checkpoint, event_bus, conn, *, reason="verifier_failed",
                        retryable=False, now_millis=None) -> None:
    """Rewind (clean) to the checkpoint, then either reject (terminal) or — for a RETRYABLE spec-claim
    deviation with attempts left — leave the task non-terminal so the bounded auto-retry can re-run it.
    A retryable rewind emits NO terminal_outcome, preserving Invariant 10 (one terminal per task)."""
    rewind_to(checkpoint, event_bus, conn, clean=True, now_millis=now_millis)
    if retryable:
        lifecycle.reset(task_id)  # non-terminal: the next attempt's queued->running is legal again
        return
    reject(task_id, reason, lifecycle, conn, event_bus, now_millis=now_millis)
