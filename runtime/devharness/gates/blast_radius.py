"""Blast-radius gate (B2.1, §S2 blast-radius gate).

Refuses a task touching more distinct files than its task class's blast_radius_limit.
A class with no declared limit (or a context with no touched paths) passes.
"""

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate
from devharness.task_classes.registry import TASK_CLASSES


class BlastRadiusGate(Gate):
    name = "blast_radius_gate"

    def check(self, context: dict):
        task_class = context.get("task_class") or getattr(context.get("planned_task"), "task_class", None)
        spec = TASK_CLASSES.get(task_class) if task_class else None
        limit = spec.blast_radius_limit if spec is not None else context.get("blast_radius_limit")
        if limit is None:
            return GateOk()
        count = len(set(context.get("touched_paths", [])))
        if count > limit:
            return GateDeny(
                reason=f"Task touches {count} files, exceeds blast_radius_limit {limit} for task_class {task_class}",
                purpose="Blast-radius invariant: tasks must respect their declared reach",
                fix="Split into multiple tasks, or raise blast_radius_limit on the task class",
            )
        return GateOk()


register_gate("blast_radius_gate", BlastRadiusGate())
