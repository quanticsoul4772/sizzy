"""Per-class gate binding (B3.1, §S2).

Each BUILD task class declares the set of gates that must fire on dispatch. All gates are
the B2.1 family reused — only the per-class membership differs (no new gate types). The
director consults a class's profile before allowing the developer to take the lock.
"""

import msgspec

# import the referenced gate modules for their registration side effect, so a profile's
# required gates are always present in GATES wherever gate_binding is imported (the director).
from devharness.gates import blast_radius, destructive, scope, verifier_attached  # noqa: F401
# B4.0: the four §S5 OSS fear-map gates (stubs until B4.2/B4.3) — imported for registration too.
from devharness.gates import sandbox, scope_guard, secret_guard, workflow_guard  # noqa: F401
from devharness.gates.base import GateDeny, evaluate
from devharness.gates.registry import GATES

# B4.0: the OSS envelope gate overlay (§S5). Layered additively onto a BUILD class's profile when a
# PlannedTask carries is_oss=True (OQ-B4-2 composition) — not a separate registry.
OSS_GATES = ["workflow_guard", "secret_guard", "scope_guard", "sandbox"]


class TaskClassGateProfile(msgspec.Struct, frozen=True, kw_only=True):
    task_class_name: str
    required_gates: list[str]  # gate names that must fire on each dispatch for this class


class GateProfileRegistrationError(RuntimeError):
    """Raised when registering a gate profile for an already-registered task class."""


GATE_PROFILES: dict[str, TaskClassGateProfile] = {}


def register_gate_profile(profile: TaskClassGateProfile) -> None:
    if profile.task_class_name in GATE_PROFILES:
        raise GateProfileRegistrationError(f"gate profile for {profile.task_class_name!r} already registered")
    GATE_PROFILES[profile.task_class_name] = profile


def clear_gate_profiles() -> None:
    """Test-isolation helper (the registry is module-global)."""
    GATE_PROFILES.clear()


def required_gates_for(task_class: str, is_oss: bool = False) -> list[str]:
    """The ordered gate names for a class, or [] if the class has no profile (e.g. new_project_scaffold).

    B4.0: when ``is_oss`` is True, the four §S5 OSS gates are appended additively (the OSS envelope
    layers onto the BUILD class's profile — OQ-B4-2 composition).
    """
    profile = GATE_PROFILES.get(task_class)
    base = list(profile.required_gates) if profile is not None else []
    return base + list(OSS_GATES) if is_oss else base


def run_admission_gates(task_class: str, context: dict, event_bus=None, is_oss: bool = False) -> list[tuple]:
    """Run the class's required gates (+ the OSS overlay when ``is_oss``) in declared order; return
    [(gate_name, result), ...].

    Each gate is run through ``evaluate`` (emitting gate_fired with its decision envelope) when an
    event_bus is supplied. Classes without a profile (new_project_scaffold) run no admission gates.
    """
    results = []
    for name in required_gates_for(task_class, is_oss):
        gate = GATES.get(name)
        if gate is None:
            continue
        result = evaluate(gate, context, event_bus) if event_bus is not None else gate.check(context)
        results.append((name, result))
    return results


def admission_denied(results) -> str | None:
    """The first denying gate's name, or None if every gate passed."""
    for name, result in results:
        if isinstance(result, GateDeny):
            return name
    return None


def register_builtin_gate_profiles() -> None:
    profiles = [
        TaskClassGateProfile(task_class_name="feature",
                             required_gates=["scope_gate", "blast_radius_gate", "destructive_command_gate", "verifier_attached_gate"]),
        TaskClassGateProfile(task_class_name="bugfix",
                             required_gates=["scope_gate", "destructive_command_gate", "verifier_attached_gate"]),
        TaskClassGateProfile(task_class_name="refactor",
                             required_gates=["scope_gate", "blast_radius_gate", "destructive_command_gate", "verifier_attached_gate"]),
        TaskClassGateProfile(task_class_name="dependency_bump",
                             required_gates=["blast_radius_gate", "destructive_command_gate", "verifier_attached_gate"]),
    ]
    for profile in profiles:
        if profile.task_class_name not in GATE_PROFILES:
            register_gate_profile(profile)


register_builtin_gate_profiles()
