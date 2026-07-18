"""Cost router (B2.1, §S8 / Invariant 13).

The task-class x cost-mode gate: enforces a class's `allowed_cost_modes`. Uses the
membership test (`cost_mode in allowed`) and the cost_mode.py predicates, so the raw
`cost_mode ==` comparisons stay confined to cost_mode.py (Invariant 13: the two
whitelisted modules are cost_mode.py and cost_router.py).
"""

from devharness.cost_mode import CostMode
from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate
from devharness.task_classes.registry import TASK_CLASSES


def allowed_cost_modes_for(task_class: str) -> list[str]:
    spec = TASK_CLASSES.get(task_class)
    if spec is not None and spec.allowed_cost_modes:
        return list(spec.allowed_cost_modes)
    return ["per_token"]  # default: write-safe


class CostModeGate(Gate):
    name = "cost_mode_gate"

    def check(self, context: dict):
        task_class = context.get("task_class")
        cost_mode: CostMode = context.get("cost_mode", "per_token")
        allowed = allowed_cost_modes_for(task_class)
        if cost_mode in allowed:
            return GateOk()
        return GateDeny(
            reason=f"cost_mode {cost_mode!r} not permitted for task_class {task_class} (allowed: {allowed})",
            purpose="Cost-mode confinement: flat-cost is permitted only for non-write classes (Invariant 13, §S8)",
            fix=f"Use one of the allowed cost modes {allowed}, or change the task class",
        )


def requires_per_token(task_class: str) -> bool:
    """True when the class does not permit flat-cost (membership test, not `==`)."""
    return "flat" not in allowed_cost_modes_for(task_class)


register_gate("cost_mode_gate", CostModeGate())
