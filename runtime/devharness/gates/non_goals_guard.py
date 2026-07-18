"""Non-goals guard — a planned task may not pursue the signed spec's explicit non-goals.

The spec's non_goals are fed to the director's decompose prompt, but nothing ENFORCED that a plan stays
within them — an operator-injected plan could pursue a non-goal (e.g. add a third-party dependency to a
"stdlib only" spec) and only the manual integration gate would catch it. This gate checks each planned
task against the non_goals before dispatch and DENIES one that pursues a non-goal.

The semantic check is injectable via ``conformance_check`` (a callable
``(description, scope, non_goals) -> violated_non_goal | None``) — the director can wire a
reasoning/parallax-backed checker. With none supplied the gate falls back to a deterministic
keyword-coverage heuristic (a non-goal is "pursued" when ALL its salient words appear in the task text),
so the gate is never silently inert. Conservative by design: it only denies on a full keyword match, to
avoid blocking legitimate work. No non_goals in context → nothing to enforce (GateOk).
"""

import re

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate

# words too generic to carry a non-goal's meaning (ignored when matching)
_STOP = frozenset({
    "the", "a", "an", "no", "not", "any", "all", "of", "to", "and", "or", "for", "with", "in", "on",
    "is", "are", "be", "this", "that", "support", "supporting", "add", "adding", "via", "use", "using",
    "only", "goal", "goals", "non", "should", "must", "task", "feature",
})


def _salient(text: str) -> list:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3 and w not in _STOP]


def keyword_coverage_violation(description, scope, non_goals, success_criteria=None):
    """Deterministic fallback: return the first non-goal whose every salient word appears in the task
    text (description + scope), else None. Conservative — full coverage required, so it does not flag a
    task that merely shares one generic word with a non-goal.

    Criteria-aware (#3b): if the task ALSO fully covers an enumerated spec success-criterion, it is
    implementing in-scope work (criteria ⊥ non-goals by construction) and is NOT flagged — this removes a
    real false-abort (a `--json`/`streaming output` feature that is itself a criterion but whose salient
    words happen to fully cover a similarly-worded non-goal). Full *criterion* coverage is required (not
    mere shared words), so a genuine out-of-scope non-goal task is not wrongly cleared; the criteria-aware
    parallax check is the preferred path and a missed non-goal is backstopped by the operator gate."""
    text = (description + " " + " ".join(scope)).lower()
    text_words = set(_salient(text))

    def _fully_covered(item) -> bool:
        words = _salient(item)
        return bool(words) and all(w in text_words for w in words)

    if any(_fully_covered(sc) for sc in (success_criteria or [])):
        return None  # in-scope: the task fully implements an enumerated success-criterion
    for ng in non_goals:
        if _fully_covered(ng):
            return ng
    return None


class NonGoalsGuard(Gate):
    name = "non_goals_guard"

    def check(self, context: dict):
        non_goals = context.get("non_goals") or []
        if not non_goals:
            return GateOk()  # nothing to enforce
        description = context.get("task_description") or ""
        scope = context.get("task_scope") or []
        success_criteria = context.get("success_criteria") or []
        checker = context.get("conformance_check")
        if checker is not None:
            violated = checker(description, scope, non_goals)  # parallax path (criteria-aware in its claim)
        else:
            # deterministic fallback — criteria-aware so an in-scope criterion-feature isn't false-flagged
            violated = keyword_coverage_violation(description, scope, non_goals, success_criteria)
        if violated:
            return GateDeny(
                reason=f"planned task pursues a signed-spec non-goal: {violated!r}",
                purpose="Spec conformance: a plan must stay within the signed spec — non-goals are explicit exclusions, not work",
                fix="Drop or rescope the task, or amend the spec's non-goals first (a non-goal is out of bounds, not a to-do)",
                evidence={"violated_non_goal": violated},
            )
        return GateOk()


register_gate("non_goals_guard", NonGoalsGuard())
