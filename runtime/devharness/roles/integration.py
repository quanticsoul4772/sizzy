"""Plan integration (B2.7).

After a dispatched task reaches a terminal outcome, the director integrates the
result and decides the plan's next move. The proj_plan projection state itself is
driven by the event handlers (task_dispatched -> executing, terminal_outcome ->
completed/blocked) to keep Invariant 8 parity; integrate() emits the director's
abort decision on a non-completed terminal and returns the plan disposition.

"Blocked pending operator review" describes the proj_plan.current_state value this
computes -- integrate() itself only emits the audit-trail director_decision event, it
does not surface anything to the operator. ConsoleTUI._next_hint() (console/tui.py) is
what actually warns the operator (rev 0.3.51) before dispatch would silently skip past
the block.
"""

import msgspec

from devharness.events.registry import DirectorDecision


def integrate(plan_artifact_id, task_id, terminal_outcome, conn, event_bus) -> str:
    """Return the plan disposition: 'completed' (advance) or 'blocked' (stop)."""
    outcome = terminal_outcome.outcome
    correlation_id = getattr(terminal_outcome, "correlation_id", "") or task_id
    if outcome == "completed":
        return "completed"  # proj_plan marked by the terminal_outcome handler; director advances
    # rejected / aborted -> the plan is blocked pending operator review
    reason = getattr(terminal_outcome, "reason", "") or getattr(terminal_outcome, "detail", "")
    event_bus.emit_sync(
        "director_decision",
        msgspec.to_builtins(DirectorDecision(decision_kind="abort", detail=f"task {task_id} {outcome}: {reason}")),
        correlation_id=correlation_id,
    )
    return "blocked"
