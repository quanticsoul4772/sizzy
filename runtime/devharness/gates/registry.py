"""Gate registry (B1.3). register_gate is the sole writer (single-write)."""

from devharness.gates.base import Gate


class GateRegistrationError(RuntimeError):
    """Raised when registering a gate name that is already registered."""


GATES: dict[str, Gate] = {}


def register_gate(name: str, gate: Gate) -> None:
    if name in GATES:
        raise GateRegistrationError(f"gate {name!r} already registered")
    GATES[name] = gate
