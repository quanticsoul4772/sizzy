"""Gate-change validator — core gates are unweakable by retro (B5.3, §S7; Inv 12).

A retro CANDIDATE that would WEAKEN a core gate (loosen / remove a signature) is auto-rejected at the
validator and logged, BEFORE it can reach operator review (B5.4). Tightening a core gate is allowed —
core gates are unweakable, not unchangeable. This module owns the **single source of truth** for the
core-gate set; B5.1's LLM filter imports CORE_GATES from here (belt-and-suspenders, same set object).
"""

import time

import msgspec

from devharness.events.registry import GateChangeRejected

# the seven enforced gates a retro may never weaken (Inv 12) — the single source of truth
CORE_GATES = frozenset({
    "workflow_guard", "secret_guard", "scope_guard", "sandbox",
    "write_lock_gate", "spec_signed_gate", "verifier_attached_gate",
})

# the change kinds that WEAKEN a gate (vs tighten / add_signature, which strengthen it)
_WEAKENING_KINDS = frozenset({"loosen", "remove_signature"})


class ValidationResult(msgspec.Struct, frozen=True, kw_only=True):
    valid: bool
    rejection_reason: str = ""


def would_weaken_core_gate(target_gate: str, change_kind: str) -> bool:
    # Normalize so a casing/whitespace variant ("WORKFLOW_GUARD", " loosen ") cannot evade the auto-reject:
    # proj_gate_change_queue.target_gate has no CHECK constraint, so a crafted candidate could carry a
    # non-canonical spelling and slip past an exact membership test (audit Inv-12 finding).
    tg = (target_gate or "").strip().lower()
    ck = (change_kind or "").strip().lower()
    return tg in CORE_GATES and ck in _WEAKENING_KINDS


def validate_gate_change_candidate(candidate_row_id, conn, event_bus, *, now_millis=None) -> ValidationResult:
    """Reject a core-gate-weakening candidate at the validator (emit gate_change_rejected, mark rejected);
    otherwise leave it pending for operator review."""
    row = conn.execute(
        "SELECT target_gate, change_kind, retro_run_correlation_id FROM proj_gate_change_queue WHERE gate_change_row_id = ?",
        (candidate_row_id,),
    ).fetchone()
    if row is None:
        return ValidationResult(valid=True)  # nothing to validate
    target_gate, change_kind, cid = row
    if would_weaken_core_gate(target_gate, change_kind):
        at = (now_millis or (lambda: int(time.time() * 1000)))()
        event_bus.emit_sync(
            "gate_change_rejected",
            msgspec.to_builtins(GateChangeRejected(
                candidate_row_id=candidate_row_id, target_gate=target_gate, change_kind=change_kind,
                rejection_reason="core_gate_weakening", auto_rejected=True, rejected_at_millis=at,
                correlation_id=cid or "retro_validator")),
            correlation_id=cid or "retro_validator",
        )
        return ValidationResult(valid=False, rejection_reason="core_gate_weakening")
    return ValidationResult(valid=True)
