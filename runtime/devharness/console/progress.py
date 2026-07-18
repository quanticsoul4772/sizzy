"""Shared build-progress formatting — the event types worth surfacing + their one-line rendering.

Extracted from the TUI (rev 0.4.3) so the web panel renders the same salient progress lines the
TUI's progress pane shows, without importing :mod:`devharness.console.tui` (which pulls Textual —
the panel host may not have it). Both surfaces import from here; the key list stays single-source.
"""

# Event types worth surfacing into a live progress panel during a build step.
PROGRESS_EVENTS = frozenset({
    "task_dispatched", "write_lock_acquired", "write_attempted", "write_applied",
    "checkpoint_taken", "rewind_performed", "verifier_outcome", "reviewer_certified",
    "reviewer_rejected", "terminal_outcome", "write_lock_released", "director_decision",
    "plan_drafted", "oss_pr_opened", "research_started", "question_asked",
    "question_answered", "assumption_flagged", "spec_drafted",
})

# The payload keys worth showing, in display order.
_SALIENT_KEYS = ("task_id", "question_id", "verifier", "passed", "outcome", "detail",
                 "decision_kind", "question_text", "answer_text", "spec_id", "plan_id", "title")


def frame_line(event_type: str, payload) -> str:
    """One progress-log line: the event type plus its salient payload fields."""
    if not isinstance(payload, dict):
        payload = {}
    bits = [event_type]
    for key in _SALIENT_KEYS:
        if key in payload:
            bits.append(f"{key}={payload[key]}")  # full value — the renderer wraps long ones
    return "  ".join(bits)
