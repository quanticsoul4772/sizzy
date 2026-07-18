"""Known-bad probe registry (B3.7).

Each probe is a context that SHOULD trigger its target gate's deny path. The runner builds the
context (via ``context_factory``, no-arg) and checks the gate still denies. Probes that need DB
state (write_lock, spec_signed) build their own seeded in-memory connection in the factory, so
every factory stays self-contained and no-arg.
"""

import sqlite3
from typing import Callable, Literal

import msgspec

# import the gate modules for their registration side effect (so GATES is populated wherever
# probes are imported), mirroring task_classes.gate_binding.
import devharness.cost_router  # noqa: F401  (registers cost_mode_gate)
from devharness.gates import (  # noqa: F401
    antibody_screen,
    blast_radius,
    destructive,
    non_goals_guard,
    sandbox,
    scope,
    scope_guard,
    secret_guard,
    spec_signed,
    verifier_attached,
    workflow_guard,
    write_lock,
)
from devharness.migrate import migrate


class KnownBadProbe(msgspec.Struct, frozen=True, kw_only=True):
    probe_name: str
    target_gate: str  # a gate_name registered in GATES
    context_factory: Callable  # () -> context dict that should trigger the gate's deny
    expected_outcome: Literal["deny"] = "deny"


class ProbeRegistrationError(RuntimeError):
    """Raised when registering a probe_name that is already registered."""


PROBES: dict[str, KnownBadProbe] = {}


def register_probe(probe: KnownBadProbe) -> None:
    if probe.probe_name in PROBES:
        raise ProbeRegistrationError(f"probe {probe.probe_name!r} already registered")
    PROBES[probe.probe_name] = probe


def clear_probes() -> None:
    """Test-isolation helper (the registry is module-global)."""
    PROBES.clear()


# --- deny-triggering context factories (no-arg, self-contained) ---

def _scope_ctx():
    return {"scope_boundary": ["src/**"], "touched_paths": ["secrets/leak.txt"], "task_id": "probe"}


def _blast_radius_ctx():
    # no task_class spec -> reads context blast_radius_limit; 3 > 0 -> deny
    return {"touched_paths": ["a.py", "b.py", "c.py"], "blast_radius_limit": 0}


def _destructive_ctx():
    return {"command_string": "git push --force origin main"}


def _verifier_attached_ctx():
    return {"verifier_ref": None}  # no attached verification plan -> deny


def _cost_mode_ctx():
    # a write class (feature) requesting flat-cost -> deny (write classes are per-token only)
    return {"task_class": "feature", "cost_mode": "flat"}


def _write_lock_ctx():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    conn.execute(
        "INSERT INTO proj_lock (lock_token, holder_role, correlation_id, acquired_at_millis) VALUES ('lk', 'developer', 'c1', 1)"
    )
    return {"conn": conn, "holder_role": "reviewer"}  # a different role -> deny


def _spec_signed_ctx():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return {"conn": conn, "correlation_id": "probe-no-spec"}  # no signed spec for this id -> deny


# B4.2: probes for the three graduated §S5 path/LOC OSS gates (sandbox stays exempt until B4.3)
def _workflow_guard_ctx():
    return {"touched_paths": [".github/workflows/ci.yml"]}  # touches a CI workflow -> deny


def _secret_guard_ctx():
    return {"diff_content": "+token = ghp_" + "a" * 36}  # a synthetic GitHub token in the diff -> deny


def _scope_guard_ctx():
    return {"diff_content": "\n".join("+line" for _ in range(501))}  # net LOC 501 > 500 -> deny


def _sandbox_ctx():
    # force the fail-closed mock launcher with no override -> deny (host-independent: does not depend
    # on whether WSL is present on the runner; B4.8 verifies the real-launcher allow path out-of-CI)
    return {"sandbox_launcher_preferred": "mock"}


def _antibody_screen_ctx():
    # seed one active antibody, then a diff that contains its pattern -> the learned-defense gate denies
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    from devharness.events.bus import EventBus
    from devharness.projections.handlers import register_handlers
    from devharness.projections.registry import ProjectionRegistry
    from devharness.retro.antibody_library import add_antibody

    registry = ProjectionRegistry()
    register_handlers(registry)
    add_antibody("os.system(", "probe-cand", "operator", conn, EventBus(conn, registry), now_millis=lambda: 1)
    return {"conn": conn, "diff_content": "os.system('rm -rf /')"}


def _non_goals_ctx():
    # a planned task that pursues a signed-spec non-goal -> the conformance guard denies (heuristic:
    # every salient word of the non-goal appears in the task text)
    return {"non_goals": ["a graphical user interface"],
            "task_description": "add a graphical user interface panel", "task_scope": ["ui/panel.py"]}


def register_builtin_probes() -> None:
    builtin = [
        KnownBadProbe(probe_name="scope_out_of_bounds", target_gate="scope_gate", context_factory=_scope_ctx),
        KnownBadProbe(probe_name="blast_radius_over_limit", target_gate="blast_radius_gate", context_factory=_blast_radius_ctx),
        KnownBadProbe(probe_name="destructive_force_push", target_gate="destructive_command_gate", context_factory=_destructive_ctx),
        KnownBadProbe(probe_name="verifier_missing", target_gate="verifier_attached_gate", context_factory=_verifier_attached_ctx),
        KnownBadProbe(probe_name="cost_mode_flat_write_class", target_gate="cost_mode_gate", context_factory=_cost_mode_ctx),
        KnownBadProbe(probe_name="write_lock_held_other_role", target_gate="write_lock_gate", context_factory=_write_lock_ctx),
        KnownBadProbe(probe_name="spec_unsigned", target_gate="spec_signed_gate", context_factory=_spec_signed_ctx),
        KnownBadProbe(probe_name="workflow_modified", target_gate="workflow_guard", context_factory=_workflow_guard_ctx),
        KnownBadProbe(probe_name="secret_in_diff", target_gate="secret_guard", context_factory=_secret_guard_ctx),
        KnownBadProbe(probe_name="loc_over_limit", target_gate="scope_guard", context_factory=_scope_guard_ctx),
        KnownBadProbe(probe_name="sandbox_unavailable", target_gate="sandbox", context_factory=_sandbox_ctx),
        KnownBadProbe(probe_name="antibody_pattern_recurred", target_gate="antibody_screen", context_factory=_antibody_screen_ctx),
        KnownBadProbe(probe_name="task_pursues_non_goal", target_gate="non_goals_guard", context_factory=_non_goals_ctx),
    ]
    for probe in builtin:
        if probe.probe_name not in PROBES:
            register_probe(probe)


register_builtin_probes()
