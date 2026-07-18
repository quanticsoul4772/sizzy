"""Iteration-rate-stakes router (B1.4).

Resolves how much reasoning a task gets: the task class sets the floor (budget +
tier minimum), the stakes signal selects a deeper path within that floor. Unknown
classes fall back to module defaults. Bound to DirectorRole so the C6 boot-check
can introspect it.
"""

from devharness.task_classes.registry import TASK_CLASSES

DEFAULT_REASONING_BUDGET_TOKENS = 20_000
DEFAULT_TIER_MINIMUM = "T2"
DEFAULT_PATH_DEPTH = 1

TIER_ORDER = {"T0": 0, "T1": 1, "T2": 2, "T3": 3}


def select_path(task_class: str, stakes_signal: float) -> tuple[int, str, int]:
    """Return (reasoning_budget_tokens, tier_minimum, path_depth) for the class+stakes."""
    spec = TASK_CLASSES.get(task_class)
    if spec is None:
        return (DEFAULT_REASONING_BUDGET_TOKENS, DEFAULT_TIER_MINIMUM, DEFAULT_PATH_DEPTH)
    # higher stakes -> bigger budget and a deeper path, but the tier floor is fixed by the class
    budget = int(spec.reasoning_budget_tokens * (1.0 + max(0.0, stakes_signal)))
    path_depth = max(1, int(round(1 + max(0.0, stakes_signal) * 2)))
    return (budget, spec.tier_minimum, path_depth)
