"""Gate-change enactment — approved gate-change candidates actually take effect (§S7, B5.4 follow-up).

Closes the asymmetry where the antibody half of the learning spine was live (approved → library →
screened against real diffs) but the gate-change half dead-ended at "approved but inert": the approval
marked the queue row but nothing changed any running gate. An approved gate-change is now ENACTED into
``proj_enacted_gate_changes`` via the ``gate_change_enacted`` event — the only enactment path, mirroring
``antibody_added`` — and gates consult ``enacted_changes_for_gate`` / ``enacted_signature_patterns`` to
honor it live.

Inv 12 still holds: a core-gate WEAKENING can never be enacted. The validator already auto-rejects such
a candidate at creation (it never reaches 'approved'); ``enact_gate_change`` re-checks belt-and-suspenders
and refuses, so even a hand-built call cannot weaken a core gate.
"""

import json
import time

import msgspec

from devharness.events.registry import GateChangeEnacted
from devharness.retro.gate_change_validator import would_weaken_core_gate


def _now(now_millis):
    return (now_millis or (lambda: int(time.time() * 1000)))()


def is_enactable(target_gate, change_kind, change_details) -> bool:
    """True iff the harness can AUTO-APPLY this change to a running gate. Today only ``add_signature`` with
    a non-empty signature: it adds an additive screening pattern a gate consults live (e.g. antibody_screen)
    and cannot weaken anything.

    The deterministic retro spine's other gate-change candidates — ``tighten`` on `verifier_attached_gate`
    (binary: a task either has a registered verifier or not — no tunable threshold) and ``loosen`` on
    `cost_mode_gate` (its allowed cost modes are structural per-task-class config, not a projection-tunable
    value) — are advisory SIGNALS with no concretely auto-applicable parameter. They are approved as
    operator decisions (recorded via `candidate_reviewed`) but the operator acts on them; auto-mutating
    enforcement from a retro signal is out of §S7's operator-in-the-loop scope. So they are NOT enacted —
    proj_enacted_gate_changes holds only what is actually in effect.

    The signature must be a non-empty, non-whitespace STRING. `bool(sig)` alone admitted a whitespace-only
    signature ("   ") — which clears antibody_screen's length floor and substring-matches nearly every
    indented diff line (a DoS on all later work) — and a non-string truthy value (e.g. 123), which then
    raises a TypeError at `sig in text` in the gate (audit findings)."""
    sig = (change_details or {}).get("signature")
    return change_kind == "add_signature" and isinstance(sig, str) and bool(sig.strip())


def enact_gate_change(target_gate, change_kind, change_details, source_candidate_id, enacted_by, conn,
                      event_bus, *, correlation_id="operator_review", now_millis=None) -> int:
    """Enact an approved gate-change → record it into the running gate config; emit gate_change_enacted;
    return its enacted_row_id. Refuses to enact a core-gate weakening (Inv 12) or a non-auto-applicable
    change (defensive — the only caller already gates on is_enactable, but this must not record an inert or
    arbitrary row into proj_enacted_gate_changes if called directly; audit)."""
    if would_weaken_core_gate(target_gate, change_kind):
        raise ValueError(f"refusing to enact a core-gate weakening ({target_gate}/{change_kind}) — Inv 12")
    if not is_enactable(target_gate, change_kind, change_details):
        raise ValueError(f"refusing to enact a non-auto-applicable change ({target_gate}/{change_kind})")
    row_id = conn.execute("SELECT COALESCE(MAX(enacted_row_id), 0) + 1 FROM proj_enacted_gate_changes").fetchone()[0]
    at = _now(now_millis)
    event_bus.emit_sync(
        "gate_change_enacted",
        msgspec.to_builtins(GateChangeEnacted(
            enacted_row_id=row_id, target_gate=target_gate, change_kind=change_kind,
            change_details=change_details or {}, source_candidate_id=source_candidate_id,
            enacted_by=enacted_by, enacted_at_millis=at, correlation_id=correlation_id)),
        correlation_id=correlation_id,
    )
    return row_id


def enacted_changes_for_gate(gate_name, conn) -> list:
    """The active (non-revoked) enacted changes for a gate, oldest first — the API a gate consults to
    honor the learning spine's gate-change half at runtime."""
    rows = conn.execute(
        "SELECT change_kind, change_details_json FROM proj_enacted_gate_changes "
        "WHERE target_gate = ? AND revoked_at_millis IS NULL ORDER BY enacted_row_id",
        (gate_name,),
    ).fetchall()
    return [{"change_kind": r[0], "change_details": json.loads(r[1] or "{}")} for r in rows]


def enacted_signature_patterns(gate_name, conn) -> list:
    """The signature texts from enacted ``add_signature`` changes for a gate — the live screening
    patterns an operator-approved gate-change contributes (the gate-change analogue of antibody text)."""
    return [
        c["change_details"]["signature"]
        for c in enacted_changes_for_gate(gate_name, conn)
        if c["change_kind"] == "add_signature" and c["change_details"].get("signature")
    ]
