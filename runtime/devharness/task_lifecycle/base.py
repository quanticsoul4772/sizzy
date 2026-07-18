"""Task lifecycle state machine (B2.6, Invariant 10).

Each task that reaches ``running`` emits exactly one terminal_outcome. The lifecycle
validates transitions and refuses a second terminal transition. correlation_id for the
terminal event is derived from the task's proj_task_started row.
"""

import time
from typing import Literal

import msgspec

from devharness.events.registry import TerminalOutcome

TaskState = Literal[
    "queued", "running", "awaiting_verifier", "awaiting_review", "completed", "rejected", "aborted"
]

TerminalStates = frozenset({"completed", "rejected", "aborted"})

LEGAL_TRANSITIONS = {
    "queued": {"running", "aborted"},
    "running": {"awaiting_verifier", "awaiting_review", "completed", "rejected", "aborted"},
    "awaiting_verifier": {"awaiting_review", "completed", "rejected", "aborted"},
    "awaiting_review": {"completed", "rejected", "aborted"},
}


class TaskLifecycleViolation(RuntimeError):
    """Raised on an illegal transition or a second terminal transition for a task."""


def _correlation_for(conn, task_id) -> str:
    row = conn.execute("SELECT correlation_id FROM proj_task_started WHERE task_id = ?", (task_id,)).fetchone()
    return row[0] if row else task_id


class TaskLifecycle:
    """Tracks task state in-process and enforces a single terminal transition."""

    def __init__(self):
        self._state: dict[str, str] = {}

    def state(self, task_id: str) -> str:
        return self._state.get(task_id, "queued")

    def reset(self, task_id: str) -> None:
        """Forget a task's in-process state so a bounded auto-retry can re-run it from 'queued'. Emits
        no event — the retry's eventual terminal is the task's single terminal_outcome (Invariant 10)."""
        self._state.pop(task_id, None)

    def transition(self, task_id, from_state, to_state, event_bus, conn, *, reason="", now_millis=None) -> None:
        current = self._state.get(task_id, "queued")
        if current in TerminalStates:
            raise TaskLifecycleViolation(
                f"task {task_id} already terminal ({current}); cannot transition to {to_state}"
            )
        if current != from_state:
            raise TaskLifecycleViolation(f"task {task_id} is {current!r}, not {from_state!r}")
        if to_state not in LEGAL_TRANSITIONS.get(from_state, set()):
            raise TaskLifecycleViolation(f"illegal transition {from_state!r} -> {to_state!r} for task {task_id}")
        self._state[task_id] = to_state
        if to_state in TerminalStates:
            terminated_at = (now_millis or (lambda: int(time.time() * 1000)))()
            correlation_id = _correlation_for(conn, task_id)
            event_bus.emit_sync(
                "terminal_outcome",
                msgspec.to_builtins(TerminalOutcome(
                    task_id=task_id, outcome=to_state, detail=reason, reason=reason,
                    correlation_id=correlation_id, terminated_at_millis=terminated_at,
                )),
                correlation_id=correlation_id,
            )
