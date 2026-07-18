"""T0 deterministic pattern-matcher (B5.1, §S7; OQ-B5-4=C — the T0 half).

Matches a RetroContext against a registered signature library, with no LLM call (no injection surface).
Each signature names a predicate (over the terminal context's preceding events) and the CANDIDATE kind
+ payload template it emits when matched. Predicates return the list of matched event_ids (empty = no
match) so the engine can attach evidence.
"""

import msgspec

from devharness.retro.base import RetroContext


class SignatureSpec(msgspec.Struct, frozen=True, kw_only=True):
    signature_name: str
    match_predicate_ref: str  # the registered name of the predicate callable
    candidate_kind: str  # antibody_candidate | gate_change_candidate
    candidate_payload_template: dict


class T0Match(msgspec.Struct, frozen=True, kw_only=True):
    signature_name: str
    candidate_kind: str
    candidate_payload_template: dict
    evidence_event_ids: list


PREDICATES: dict[str, object] = {}
PATTERN_SIGNATURES: dict[str, SignatureSpec] = {}


class SignatureRegistrationError(RuntimeError):
    """Raised when registering a signature/predicate name that is already registered."""


def register_predicate(ref: str, fn) -> None:
    if ref in PREDICATES:
        raise SignatureRegistrationError(f"predicate {ref!r} already registered")
    PREDICATES[ref] = fn


def register_signature(spec: SignatureSpec) -> None:
    """Sole writer to PATTERN_SIGNATURES (single-write enforced)."""
    if spec.signature_name in PATTERN_SIGNATURES:
        raise SignatureRegistrationError(f"signature {spec.signature_name!r} already registered")
    PATTERN_SIGNATURES[spec.signature_name] = spec


# --- predicate helpers over the terminal context's preceding events ---
def _gate_denied(ctx: RetroContext, gate_name: str, reason_substr: str | None = None) -> list:
    ids = []
    for ev in ctx.preceding_events:
        if ev.get("event_type") != "gate_fired":
            continue
        p = ev.get("payload", {})
        if p.get("gate") == gate_name and p.get("decision") == "deny" and (reason_substr is None or reason_substr in (p.get("reason") or "")):
            ids.append(ev.get("event_id", ""))
    return ids


def _intake_rejected(ctx: RetroContext, rejection_reason: str) -> list:
    ids = []
    for ev in ctx.preceding_events:
        if ev.get("event_type") != "intake_decision":
            continue
        p = ev.get("payload", {})
        if p.get("decision") == "rejected" and p.get("rejection_reason") == rejection_reason:
            ids.append(ev.get("event_id", ""))
    return ids


def _verifier_failed(ctx: RetroContext, reason_substr: str) -> list:
    ids = []
    for ev in ctx.preceding_events:
        if ev.get("event_type") != "verifier_outcome":
            continue
        p = ev.get("payload", {})
        # B5.7 acceptance fix: match the real VerifierOutcome shape (passed: bool, detail: str). The
        # original predicate read outcome/reason — fields VerifierOutcome never carries — so these three
        # verifier_failure signatures were dead against real events (never covered by a B5.1 test).
        if p.get("passed") is False and reason_substr in (p.get("detail") or ""):
            ids.append(ev.get("event_id", ""))
    return ids


def _budget_exceeded(ctx: RetroContext, budget_kind: str) -> list:
    ids = []
    for ev in ctx.preceding_events:
        if ev.get("event_type") != "budget_exceeded":
            continue
        p = ev.get("payload", {})
        if p.get("budget_kind") == budget_kind and p.get("action_taken") == "abort":
            ids.append(ev.get("event_id", ""))
    return ids


def _brier_drift(ctx: RetroContext) -> list:
    return ["calibration_snapshot"] if (ctx.calibration_snapshot or {}).get("brier", 0.0) > 0.20 else []


def _event_present(ctx: RetroContext, event_type: str) -> list:
    """Match iff a `event_type` event is in the context (the signal-retro trigger puts the single signal
    event in `preceding_events`); returns its event_id as evidence."""
    return [ev.get("event_id", "") for ev in ctx.preceding_events if ev.get("event_type") == event_type]


def _register_builtin_signatures() -> None:
    # gate denies -> antibody (a learning about a known-bad write/intent)
    gate_denies = [
        ("gate_deny_workflow_modified", lambda c: _gate_denied(c, "workflow_guard"), "workflow modification denied at admission"),
        ("gate_deny_secret_path", lambda c: _gate_denied(c, "secret_guard", "path"), "secret-named file write denied (path axis)"),
        ("gate_deny_secret_content", lambda c: _gate_denied(c, "secret_guard", "content"), "secret content denied in diff (content axis)"),
        ("gate_deny_loc_over_limit", lambda c: _gate_denied(c, "scope_guard"), "cumulative LOC over limit denied"),
        ("gate_deny_sandbox_unavailable", lambda c: _gate_denied(c, "sandbox"), "execution outside the sandbox denied"),
    ]
    intake_rejections = [
        ("intake_reject_license", lambda c: _intake_rejected(c, "license_disallowed"), "intake rejected: license disallowed"),
        ("intake_reject_maintainer", lambda c: _intake_rejected(c, "maintainer_unverified"), "intake rejected: maintainer unverified"),
        ("intake_reject_injection", lambda c: _intake_rejected(c, "injection_detected"), "intake rejected: injection detected"),
        ("intake_reject_cooldown", lambda c: _intake_rejected(c, "requester_in_cooldown"), "intake rejected: requester in cooldown"),
    ]
    for name, pred, text in gate_denies + intake_rejections:
        register_predicate(name, pred)
        register_signature(SignatureSpec(signature_name=name, match_predicate_ref=name,
                                         candidate_kind="antibody_candidate", candidate_payload_template={"pattern_text": text}))

    # verifier failures -> gate_change (propose tightening the verifier's expectation)
    verifier_failures = [
        ("verifier_failure_baseline_fail", lambda c: _verifier_failed(c, "baseline"), "baseline_should_fail"),
        ("verifier_failure_post_pass", lambda c: _verifier_failed(c, "post"), "post_should_pass"),
        ("verifier_failure_behavior_change", lambda c: _verifier_failed(c, "behavior"), "behavior_preserving"),
    ]
    for name, pred, axis in verifier_failures:
        register_predicate(name, pred)
        register_signature(SignatureSpec(signature_name=name, match_predicate_ref=name, candidate_kind="gate_change_candidate",
                                         candidate_payload_template={"target_gate": "verifier_attached_gate", "change_kind": "tighten",
                                                                     "change_details": {"axis": axis}}))

    # caps exceeded -> gate_change (propose revisiting the cap)
    caps = [
        ("cap_exceeded_wall_clock", lambda c: _budget_exceeded(c, "oss_wall_clock"), "oss_wall_clock"),
        ("cap_exceeded_usd", lambda c: _budget_exceeded(c, "oss_usd"), "oss_usd"),
    ]
    for name, pred, kind in caps:
        register_predicate(name, pred)
        register_signature(SignatureSpec(signature_name=name, match_predicate_ref=name, candidate_kind="gate_change_candidate",
                                         candidate_payload_template={"target_gate": "cost_mode_gate", "change_kind": "loosen",
                                                                     "change_details": {"budget_kind": kind}}))

    # calibration drift -> gate_change (propose recalibration)
    register_predicate("calibration_brier_drift", _brier_drift)
    register_signature(SignatureSpec(signature_name="calibration_brier_drift", match_predicate_ref="calibration_brier_drift",
                                     candidate_kind="gate_change_candidate",
                                     candidate_payload_template={"target_gate": "verifier_attached_gate", "change_kind": "tighten",
                                                                 "change_details": {"reason": "brier_drift_over_0.20"}}))

    # §S7 learning-loop closure: monitor/fault-injection regressions -> advisory gate_change. `tighten` on a
    # NON-core target_gate: the Inv-12 validator never auto-rejects it (not a weakening), and only
    # `add_signature` auto-enacts, so it stays operator-review-only. The specific invariant#/fault detail is
    # reachable via evidence_event_ids (the signal event itself).
    #
    # These two are SIGNAL-ONLY (gated on `not c.terminal_outcome_event`): the SignalRetroScheduler builds
    # a context with terminal_outcome_event={} while the terminal-triggered RetroScheduler fills it. Without
    # the gate they'd ALSO fire from the terminal path when an invariant_violated sits in a re-driven
    # terminal's preceding_events (same correlation, lower seq) — a duplicate + wrongly-attributed candidate.
    signal_regressions = [
        ("monitor_invariant_violated",
         lambda c: _event_present(c, "invariant_violated") if not c.terminal_outcome_event else [],
         "invariant_monitor",
         "a live behavioral-invariant breach was detected — review the guard/verifier for this invariant"),
        ("loop_fault_regression",
         lambda c: _event_present(c, "fault_handling_regression") if not c.terminal_outcome_event else [],
         "fault_handling",
         "a loop-fault probe caught the harness mishandling an injected fault — review the fault-handling path"),
    ]
    for name, pred, target, reason in signal_regressions:
        register_predicate(name, pred)
        register_signature(SignatureSpec(signature_name=name, match_predicate_ref=name,
                                         candidate_kind="gate_change_candidate",
                                         candidate_payload_template={"target_gate": target, "change_kind": "tighten",
                                                                     "change_details": {"reason": reason}}))


_register_builtin_signatures()


def match_signatures(retro_context: RetroContext) -> list:
    """Run every registered signature's predicate; return the T0Matches that fired."""
    matches = []
    for name, spec in PATTERN_SIGNATURES.items():
        evidence = PREDICATES[spec.match_predicate_ref](retro_context)
        if evidence:
            matches.append(T0Match(signature_name=name, candidate_kind=spec.candidate_kind,
                                   candidate_payload_template=dict(spec.candidate_payload_template),
                                   evidence_event_ids=list(evidence)))
    return matches
