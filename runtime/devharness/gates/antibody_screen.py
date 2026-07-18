"""Antibody screen gate (#M7, §S7, Inv 11).

Wires the learned antibody library into a LIVE screen: a realized diff (or any `screen_text`) that
contains an active antibody's `pattern_text` is a recurrence of a retro-learned, operator-approved
known-bad pattern. `match_against_text` existed but had no caller — antibodies were learned and
approved but never applied to anything. Text-only (Inv 11): the gate substring-matches against the
active library; it never executes a pattern. No library in context (e.g. the synthetic boot-check
context) passes.
"""

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate
from devharness.retro.antibody_library import match_against_text
from devharness.retro.enacted_gate_changes import enacted_signature_patterns

# patterns shorter than this are too generic to screen on (a 1-2 char antibody would match almost any
# diff); the operator approves antibody text, but this is a defensive floor (review #2). NOTE (audit): the
# match is a raw substring, so a short generic operator-approved (or federated) antibody can substring-hit
# an unrelated incremental OSS diff and hard-abort it. The OPERATOR's approval of the pattern text is the
# real guard (a too-generic pattern is an authoring choice); this coarse floor is left as-is deliberately
# rather than raised — a higher floor would reject legitimately-short meaningful antibodies (e.g. `eval(`).
_MIN_PATTERN_LEN = 3


def _screened_text(raw: str) -> str:
    """The text to screen. For a unified diff, only the ADDED content (lines starting with '+' but not
    the '+++' header) — never removed/context/header lines: screening a removed line would deny the very
    change that DELETES a known-bad pattern (review #1), and context lines flag code this change did not
    introduce. Non-diff `screen_text` (no hunk markers) is screened whole."""
    lines = raw.splitlines()
    if not any(ln.startswith(("+", "-", "@@")) for ln in lines):
        return raw
    return "\n".join(ln[1:] for ln in lines if ln.startswith("+") and not ln.startswith("+++"))


class AntibodyScreenGate(Gate):
    name = "antibody_screen"

    def check(self, context: dict):
        conn = context.get("conn")
        if conn is None:
            return GateOk()  # nothing to screen against
        text = _screened_text(context.get("screen_text") or context.get("diff_content") or "")
        # screen against the antibody library AND any enacted add_signature gate-changes targeting this
        # gate — an operator-approved gate-change is now live, not inert (the gate-change analogue of an
        # antibody). Both are text patterns; neither is ever executed (Inv 11).
        patterns = list(match_against_text(text, conn))
        for sig in enacted_signature_patterns("antibody_screen", conn):
            if sig in text:
                patterns.append(sig)
        matches = [m for m in patterns if len(m) >= _MIN_PATTERN_LEN]
        if matches:
            return GateDeny(
                reason=f"realized change matches {len(matches)} learned known-bad pattern(s): {sorted(set(matches))}",
                purpose="Learned defense: a retro-learned, operator-approved known-bad pattern (antibody or enacted gate-change) recurred",
                fix="Remove the flagged pattern from the change, or have the operator revoke the stale antibody / gate-change",
            )
        return GateOk()


register_gate("antibody_screen", AntibodyScreenGate())
