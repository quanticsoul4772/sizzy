"""Gate framework (B1.3).

A gate is a structural predicate enforced in harness code. Its result is either
``GateOk`` or a ``GateDeny`` carrying the reason/purpose/fix envelope (commitment 9):
operators never see a bare "blocked". ``evaluate`` runs a gate and records the
outcome as a ``gate_fired`` event.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import msgspec

from devharness.events.registry import GateFired


@dataclass(frozen=True)
class GateOk:
    """A passing gate result. ``reason`` is optional (default ""); B4.0 stub gates use it
    to mark ``not_yet_implemented_in_B4.0`` until they graduate to real bodies in B4.2/B4.3.
    ``evidence`` (optional, default {}) carries structured detail for the operator (e.g. the
    resolved sandbox launcher) — symmetric with GateDeny.evidence (B4.3)."""

    reason: str = ""
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GateDeny:
    """A denying gate result with the full reason/purpose/fix envelope (commitment 9).

    ``evidence`` (optional, default {}) carries structured detail for the operator — e.g. the
    matched paths/patterns or the computed LOC — WITHOUT leaking sensitive matched text (B4.2)."""

    reason: str
    purpose: str
    fix: str
    evidence: dict = field(default_factory=dict)

    def __post_init__(self):
        if not (self.reason and self.purpose and self.fix):
            raise ValueError("GateDeny requires non-empty reason, purpose, and fix")


class Gate(ABC):
    """A structural gate. Identity is its enforced check, not a prompt."""

    name: str = "gate"

    @abstractmethod
    def check(self, context: dict):  # -> GateOk | GateDeny
        ...


def evaluate(gate: Gate, context: dict, event_bus):
    """Run a gate, emit gate_fired with its decision + envelope, and return the result."""
    result = gate.check(context)
    correlation_id = context.get("correlation_id")
    if isinstance(result, GateDeny):
        fired = GateFired(gate=gate.name, decision="deny", reason=result.reason, purpose=result.purpose, fix=result.fix)
    else:
        # capture an allow's reason (e.g. a B4.2 override marker) so the operator can audit it
        fired = GateFired(gate=gate.name, decision="allow", reason=getattr(result, "reason", "") or "", purpose="", fix="")
    event_bus.emit_sync("gate_fired", msgspec.to_builtins(fired), correlation_id=correlation_id)
    return result
