"""Agent-role base (B1.0; substrate trimmed in the constitution v0.2.0 amendment).

The abstract advisory-role base + the C10 progress metric + the budget-exceeded exception. The earlier
per-role-budget substrate (``RoleSpec`` / ``spawn_role`` / ``RoleWorker`` / the role registry) was retired
in the constitution v0.2.0 amendment: the per-role-budget boot check (``check_role_context_budget_declared``)
was vacuous, and the real roles grew their own ``run()`` loops rather than ``spawn_role``. The live cost
model is per-task caps (``oss/caps.py``) + the director's per-task tier minima, not a per-role budget.
"""

from abc import ABC, abstractmethod


class BudgetExceeded(RuntimeError):
    """Raised when an accumulated cost exceeds a declared budget (e.g. the director's reasoning budget)."""


def progress_from_messages(messages) -> int:
    """C10 progress metric: count tool-call blocks; text-only output is not progress."""
    count = 0
    for message in messages:
        content = getattr(message, "content", None)
        if not content:
            continue
        for block in content:
            if type(block).__name__ == "ToolUseBlock":
                count += 1
    return count


class AgentRole(ABC):
    """Abstract advisory role. Concrete roles (research, director, developer, reviewer) subclass."""

    setting_sources: list = []  # commitment 3 posture

    @abstractmethod
    async def run(self, prompt: str):  # pragma: no cover - interface
        ...
