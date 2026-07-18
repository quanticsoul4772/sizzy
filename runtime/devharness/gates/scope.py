"""Scope gate (B2.1, §S2 scope gate).

Refuses an edit to a file outside the task's declared scope_boundary. The boundary
is a list of globs; a touched path must match at least one. Gracefully passes a
context that declares no touched paths (e.g. the synthetic boot-check context).
"""

from fnmatch import fnmatch

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate


def _boundary(context: dict) -> list[str]:
    if context.get("scope_boundary") is not None:
        return list(context["scope_boundary"])
    planned = context.get("planned_task")
    return list(getattr(planned, "scope_boundary", []) or [])


class ScopeGate(Gate):
    name = "scope_gate"

    def check(self, context: dict):
        boundary = _boundary(context)
        task_id = context.get("task_id") or getattr(context.get("planned_task"), "task_id", "<unknown>")
        for path in context.get("touched_paths", []):
            if not any(fnmatch(path, glob) for glob in boundary):
                return GateDeny(
                    reason=f"File path {path} outside declared scope_boundary for task {task_id}",
                    purpose="Scope invariant: tasks touch only files declared in their scope_boundary",
                    fix="Update the task's scope_boundary to include the path, or work within the existing boundary",
                )
        return GateOk()


register_gate("scope_gate", ScopeGate())
