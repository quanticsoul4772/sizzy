"""Task class registry (B1.4). register_task_class is the sole writer (single-write).

B1.4 ships with the registry empty; concrete classes land in B2 onward.
"""

from devharness.task_classes.base import TaskClassSpec


class TaskClassRegistrationError(RuntimeError):
    """Raised when registering a task-class name that is already registered."""


TASK_CLASSES: dict[str, TaskClassSpec] = {}


def register_task_class(spec: TaskClassSpec) -> None:
    if spec.name in TASK_CLASSES:
        raise TaskClassRegistrationError(f"task class {spec.name!r} already registered")
    TASK_CLASSES[spec.name] = spec


def clear_task_classes() -> None:
    """Test-isolation helper (the registry is module-global)."""
    TASK_CLASSES.clear()


_TIER_ORDER = {"T0": 0, "T1": 1, "T2": 2, "T3": 3}


def batch_writer_tier(task_class_names) -> str:
    """The writer tier for a BATCH of tasks that share one developer model (rev 0.3.85): the HIGHEST
    class tier across the batch, so a mixed-class batch never downgrades a frontier-tier task. An
    unknown class or an empty batch falls back to T2 (frontier). Returns a tier string; the caller
    applies ``models.model_for_tier`` to get a concrete model."""
    tiers = []
    for name in task_class_names:
        spec = TASK_CLASSES.get(name)
        tiers.append(spec.tier_minimum if spec else "T2")
    return max(tiers, key=lambda t: _TIER_ORDER.get(t, 2)) if tiers else "T2"
