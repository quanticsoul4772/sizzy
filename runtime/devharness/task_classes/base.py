"""Task class spec (B1.4).

Each task class declares a director reasoning budget and a tier minimum (§S2).
B1.4 ships no concrete classes; real entries land in B2 onward.
"""

import msgspec


class TaskClassSpec(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    reasoning_budget_tokens: int
    tier_minimum: str  # T0 | T1 | T2 | T3
    dominant_gate_sensitivity: str
    blast_radius_limit: int | None = None  # per-class file-count cap (B2.1; None = unbounded)
    allowed_cost_modes: list[str] = msgspec.field(default_factory=list)  # §S8; write classes force per_token
