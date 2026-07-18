"""Cost mode (B2.1, §S8 / Invariant 13).

The `session.cost_mode` field and the *only* place `cost_mode ==` comparisons are
permitted (alongside cost_router.py). Per §S8: per-token is forced for any class with
write authority; flat-cost is permitted only for maintenance/consolidation classes.
"""

from dataclasses import dataclass
from typing import Literal

CostMode = Literal["per_token", "flat"]

DEFAULT_COST_MODE: CostMode = "per_token"


@dataclass(frozen=True)
class SessionCostMode:
    """The cost_mode field carried on a task/session record."""

    cost_mode: CostMode = DEFAULT_COST_MODE


def is_per_token(cost_mode: CostMode) -> bool:
    return cost_mode == "per_token"


def is_flat(cost_mode: CostMode) -> bool:
    return cost_mode == "flat"
