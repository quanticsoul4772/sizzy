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

# The elicit payload's key strings — presence means "machine JSON, not prose". Detection by marker
# (rev 0.4.29 review): a brace heuristic both false-positived a legitimate brace-led question and
# false-negatived a code-fenced payload; and PLAIN-PROSE question_text (a confirmation turn, an
# operator passthrough) must render FULL, not sliced at the summary length.
_ELICIT_MARKERS = ('"divergence_points"', '"assumed_objective"')


def _display_value(key: str, value) -> str:
    """rev 0.4.28/0.4.29 (the charfreq drive): ``question_text`` may store the RAW elicit JSON, and
    the full-value render walled the progress pane with 1.4KB of wrapped JSON (the rev-0.4.12
    readable fix covered the question card + A-prompt but never this line). Only PAYLOAD-shaped
    question_text is summarized — plain-prose questions and every other key keep the original
    full-value render deliberately (a generic cap would truncate verifier failure ``detail``, the
    operator's only diagnostics surface in the pane; the renderer wraps long ones)."""
    text = str(value)
    if key != "question_text" or not any(m in text for m in _ELICIT_MARKERS):
        return text
    try:
        from devharness.roles.research import readable_question_text
    except ImportError:
        return "(elicit payload)"  # degrade to a marker, never a raw machine-JSON slice
    readable = readable_question_text(text)
    if any(m in readable for m in _ELICIT_MARKERS):
        # extraction failed (a mid-object-truncated or code-fenced payload falls through to a raw
        # slice that still carries the payload keys) — never show machine JSON in the pane
        return "(elicit payload — unparseable)"
    return readable


def frame_line(event_type: str, payload) -> str:
    """One progress-log line: the event type plus its salient payload fields."""
    if not isinstance(payload, dict):
        payload = {}
    bits = [event_type]
    for key in _SALIENT_KEYS:
        if key in payload:
            bits.append(f"{key}={_display_value(key, payload[key])}")
    return "  ".join(bits)
