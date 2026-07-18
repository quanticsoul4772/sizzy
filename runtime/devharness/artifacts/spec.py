"""Spec-artifact schema (B1.1).

The research role's output: a reviewed, self-contained spec with an explicit
assumptions-and-low-confidence section. ``assumptions`` is required non-empty —
enforced at decode/convert by ``Meta(min_length=1)`` and at the business level by
``is_valid`` (direct construction bypasses msgspec constraints).
"""

from typing import Annotated

import msgspec


class Assumption(msgspec.Struct, frozen=True, kw_only=True):
    text: str
    confidence: float  # 0.0-1.0
    low_confidence_flag: bool
    schema_version: int = 1


class SpecArtifact(msgspec.Struct, frozen=True, kw_only=True):
    problem: str
    scope: str
    non_goals: list[str]
    interfaces: list[str]
    success_criteria: list[str]
    verification_plan: str
    assumptions: Annotated[list[Assumption], msgspec.Meta(min_length=1)]  # required non-empty
    correlation_id: str
    signed: bool = False
    signed_at_millis: int | None = None
    signed_by: str | None = None
    schema_version: int = 1

    def sign(self, signed_by: str, signed_at_millis: int) -> "SpecArtifact":
        """Return a new signed copy carrying the operator's signature."""
        return msgspec.structs.replace(
            self, signed=True, signed_by=signed_by, signed_at_millis=signed_at_millis
        )

    def is_valid(self) -> bool:
        """True iff all required fields are populated and assumptions is non-empty."""
        if not self.assumptions:
            return False
        required_text = (self.problem, self.scope, self.verification_plan, self.correlation_id)
        if not all(required_text):
            return False
        if not self.success_criteria:
            return False
        return True
