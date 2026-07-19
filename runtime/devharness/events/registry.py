"""Typed event payloads (B0.4) — mirrors spec §Data model, event catalog.

Each payload is a frozen, keyword-only ``msgspec.Struct`` carrying
``schema_version``; payload evolution is a ``schema_version`` bump, never an
in-place field rename. ``EVENT_TYPES`` maps the ``events.event_type`` string to
its payload struct. Field names are the conventional set chosen at rev 0.3.2.
"""

from typing import Literal

import msgspec


class ConnectionOpened(msgspec.Struct, frozen=True, kw_only=True):
    connection_id: str
    role: str
    schema_version: int = 1


class RoleTransitioned(msgspec.Struct, frozen=True, kw_only=True):
    from_role: str
    to_role: str
    schema_version: int = 1


class IntentProposed(msgspec.Struct, frozen=True, kw_only=True):
    intent_id: str
    call_class: str  # mutation | read | harness
    summary: str
    schema_version: int = 1


class GateFired(msgspec.Struct, frozen=True, kw_only=True):
    gate: str
    decision: str  # allow | deny
    reason: str
    purpose: str
    fix: str
    schema_version: int = 1


class VerifierOutcome(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    verifier: str
    passed: bool
    detail: str
    evidence: dict = msgspec.field(default_factory=dict)  # B2.2: command + result evidence
    schema_version: int = 1


class CheckpointTaken(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    checkpoint_id: str
    ref: str
    worktree_path: str = ""  # B2.4 additive (default keeps pre-B2.4 constructions valid)
    git_commit_sha: str = ""  # B2.4 additive
    taken_at_millis: int = 0  # B2.4 additive
    schema_version: int = 1


class TerminalOutcome(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    outcome: str  # completed | rejected | aborted (B2.6 lifecycle terminals; B0 also used failed/abstained)
    detail: str
    reason: str = ""  # B2.6 additive (default keeps pre-B2.6 constructions valid)
    correlation_id: str = ""  # B2.6 additive
    terminated_at_millis: int = 0  # B2.6 additive
    schema_version: int = 1


# --- B1 research-loop event payloads (rev 0.3.2 catalog, plan v0.4.1) ---


class ResearchStarted(msgspec.Struct, frozen=True, kw_only=True):
    research_id: str
    topic: str
    schema_version: int = 1


class QuestionAsked(msgspec.Struct, frozen=True, kw_only=True):
    research_id: str
    question_id: str
    question_text: str
    schema_version: int = 1


class QuestionAnswered(msgspec.Struct, frozen=True, kw_only=True):
    question_id: str
    answer_text: str
    correlation_id: str
    answered_at_millis: int
    schema_version: int = 1


class AssumptionFlagged(msgspec.Struct, frozen=True, kw_only=True):
    research_id: str
    text: str
    confidence: float  # 0.0-1.0 (mirrors artifacts.spec.Assumption)
    low_confidence_flag: bool
    schema_version: int = 1


class SpecDrafted(msgspec.Struct, frozen=True, kw_only=True):
    spec_id: str
    title: str
    schema_version: int = 1


class SpecSigned(msgspec.Struct, frozen=True, kw_only=True):
    spec_id: str
    signer: str
    signed_at_millis: int  # B1.6: enables proj_signed_spec.signed_at_millis + the signed-spec tile
    schema_version: int = 1


class ExplorePassCompleted(msgspec.Struct, frozen=True, kw_only=True):
    repo_path: str
    summary_ref: str
    file_count: int  # B1.6: counts carried so the event-driven explore tile can render them
    manifest_count: int
    test_count: int
    ci_count: int
    schema_version: int = 1


class PlanDrafted(msgspec.Struct, frozen=True, kw_only=True):
    plan_id: str
    spec_id: str
    task_count: int
    schema_version: int = 1


class DirectorDecision(msgspec.Struct, frozen=True, kw_only=True):
    decision_kind: Literal["fork", "sequencing", "abort"]  # required discriminator
    detail: str
    schema_version: int = 1


class BudgetExceeded(msgspec.Struct, frozen=True, kw_only=True):
    # The generic budget-overrun event (OQ-B4-3 resolved to reuse this rather than mint oss_cap_exceeded).
    # B2.x per-role budgets populate role/limit/spent; B4.6 OSS caps/cooldowns/revocation populate the
    # subject_id/action_taken/limit_value/observed_value/reason fields. budget_kind discriminates.
    budget_kind: Literal[
        "reasoning", "token", "wall_clock",  # B2.x per-role budgets
        "oss_wall_clock", "oss_usd", "oss_requester_cooldown", "requester_revoked",  # B4.6 OSS
    ]
    # B2.x fields (default-populated so OSS emits need not set them)
    role: str = ""
    limit: float = 0.0
    spent: float = 0.0
    # B4.6 OSS fields (default-populated so B2.x emits need not set them)
    limit_value: float | None = None  # cap kinds only; None for cooldown/revoked
    observed_value: float | None = None  # cap kinds only; None for cooldown/revoked
    action_taken: str = ""  # abort | refuse | revoke
    subject_id: str = ""  # oss_task_id (caps) | requester_id (cooldown/revoked)
    reason: str = ""  # non-empty when budget_kind == requester_revoked
    exceeded_at_millis: int = 0
    correlation_id: str = ""
    schema_version: int = 1

    def __post_init__(self):
        if self.budget_kind == "requester_revoked" and not self.reason:
            raise ValueError("BudgetExceeded(requester_revoked) requires a non-empty reason")


class WriteLockAcquired(msgspec.Struct, frozen=True, kw_only=True):
    lock_token: str
    holder_role: str
    correlation_id: str
    acquired_at_millis: int
    schema_version: int = 1


class WriteLockReleased(msgspec.Struct, frozen=True, kw_only=True):
    lock_token: str
    holder_role: str
    correlation_id: str
    released_at_millis: int
    schema_version: int = 1


class TaskStarted(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    role: str
    worktree_path: str
    correlation_id: str
    started_at_millis: int
    schema_version: int = 1


class WriteAttempted(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    worktree_path: str
    target_path: str
    action_kind: str  # write_file | append_to_file
    correlation_id: str
    attempted_at_millis: int
    predicted_success: float = 0.5  # B2.8 additive: the developer's predicted P(success) for this mutation
    task_class: str = ""  # B3.0 additive: the task's class (per-class Brier filtering)
    schema_version: int = 1


class WriteApplied(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    worktree_path: str
    target_path: str
    action_kind: str  # write_file | append_to_file
    correlation_id: str
    applied_at_millis: int
    observed_success: bool = True  # B2.8 additive: whether the write actually applied
    task_class: str = ""  # B3.0 additive: the task's class (per-class Brier filtering)
    schema_version: int = 1


class RewindPerformed(msgspec.Struct, frozen=True, kw_only=True):
    checkpoint_id: str
    task_id: str
    worktree_path: str
    git_commit_sha: str
    correlation_id: str
    rewound_at_millis: int
    schema_version: int = 1


class ReviewerCertified(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    reviewer_session_id: str
    evidence: dict
    correlation_id: str
    certified_at_millis: int
    schema_version: int = 1


class ReviewerRejected(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    reviewer_session_id: str
    reason: str
    evidence: dict
    correlation_id: str
    rejected_at_millis: int
    schema_version: int = 1

    def __post_init__(self):
        if not self.reason:
            raise ValueError("ReviewerRejected requires a non-empty reason")


class TaskDispatched(msgspec.Struct, frozen=True, kw_only=True):
    plan_id: str
    task_id: str
    dispatched_to_role: str
    dispatched_by_role: str
    correlation_id: str
    dispatched_at_millis: int
    task_class: str = ""  # B3.0 additive: the dispatched task's class (per-task tracking)
    dependency_task_ids: str = ""  # B3.0 additive: JSON list of task_ids this task depends on
    schema_version: int = 1


class OssTaskIntake(msgspec.Struct, frozen=True, kw_only=True):
    upstream_repo: str
    license_spdx: str
    requester_id: str
    target_branch: str
    intake_at_millis: int
    correlation_id: str
    schema_version: int = 1


class AntibodyAdded(msgspec.Struct, frozen=True, kw_only=True):
    antibody_row_id: int
    pattern_text: str  # non-empty (validated); antibodies are text only (Inv 11)
    source_candidate_id: str
    added_by: str
    added_at_millis: int
    correlation_id: str
    schema_version: int = 1

    def __post_init__(self):
        if not self.pattern_text:
            raise ValueError("AntibodyAdded requires a non-empty pattern_text")


class AntibodyRevoked(msgspec.Struct, frozen=True, kw_only=True):
    antibody_row_id: int
    reason: str  # non-empty (validated)
    revoked_by: str
    revoked_at_millis: int
    correlation_id: str
    schema_version: int = 1

    def __post_init__(self):
        if not self.reason:
            raise ValueError("AntibodyRevoked requires a non-empty reason")


class GateChangeEnacted(msgspec.Struct, frozen=True, kw_only=True):
    # An approved gate-change candidate ENACTED into the running gate config (proj_enacted_gate_changes) —
    # the only path from 'approved' to in-effect, mirroring antibody_added. A core-gate weakening can
    # never be enacted (Inv 12, enforced in enact_gate_change).
    enacted_row_id: int
    target_gate: str
    change_kind: Literal["tighten", "loosen", "add_signature", "remove_signature"]
    change_details: dict
    source_candidate_id: str
    enacted_by: str
    enacted_at_millis: int
    correlation_id: str
    schema_version: int = 1


class CandidateReviewed(msgspec.Struct, frozen=True, kw_only=True):
    candidate_row_id: int
    candidate_kind: Literal["antibody_candidate", "gate_change_candidate"]
    review_state: Literal["approved", "rejected"]
    reviewed_by: str
    review_reason: str  # non-empty (validated) when review_state == 'rejected'; optional when 'approved'
    reviewed_at_millis: int
    correlation_id: str
    schema_version: int = 1

    def __post_init__(self):
        if self.review_state == "rejected" and not self.review_reason:
            raise ValueError("CandidateReviewed(rejected) requires a non-empty review_reason")


class GateChangeRejected(msgspec.Struct, frozen=True, kw_only=True):
    candidate_row_id: int
    target_gate: str
    change_kind: str
    rejection_reason: str  # non-empty (validated); "core_gate_weakening" for validator auto-rejects
    auto_rejected: bool  # True for validator-driven rejections (the only producer in B5.3)
    rejected_at_millis: int
    correlation_id: str
    schema_version: int = 1

    def __post_init__(self):
        if not self.rejection_reason:
            raise ValueError("GateChangeRejected requires a non-empty rejection_reason")


class CandidateRejected(msgspec.Struct, frozen=True, kw_only=True):
    candidate_row_id: int
    candidate_kind: Literal["antibody_candidate", "gate_change_candidate"]
    rejected_by: str
    reason: str
    rejected_at_millis: int
    correlation_id: str
    schema_version: int = 1


class AntibodyCandidate(msgspec.Struct, frozen=True, kw_only=True):
    retro_run_correlation_id: str
    signature_name: str  # T0 signature name, "quarantine_blocked", or "" for an LLM proposal
    pattern_text: str  # the known-bad pattern text (antibodies are text only — Inv 11)
    evidence_event_ids: list[str]
    source: Literal["t0", "llm", "quarantine"]
    created_at_millis: int
    correlation_id: str
    candidate_kind: Literal["antibody_candidate"] = "antibody_candidate"
    schema_version: int = 1

    def __post_init__(self):
        if not self.pattern_text:
            raise ValueError("AntibodyCandidate requires a non-empty pattern_text")


class GateChangeCandidate(msgspec.Struct, frozen=True, kw_only=True):
    retro_run_correlation_id: str
    signature_name: str
    target_gate: str
    change_kind: Literal["tighten", "loosen", "add_signature", "remove_signature"]
    change_details: dict
    evidence_event_ids: list[str]
    source: Literal["t0", "llm"]
    created_at_millis: int
    correlation_id: str
    candidate_kind: Literal["gate_change_candidate"] = "gate_change_candidate"
    schema_version: int = 1


class MemoryEntryCreated(msgspec.Struct, frozen=True, kw_only=True):
    entry_id: str
    entry_type: str
    entry_payload_json: str  # JSON-encoded type-specific payload
    source_project: str
    created_at_millis: int
    correlation_id: str
    schema_version: int = 1


class MemoryEntryVerified(msgspec.Struct, frozen=True, kw_only=True):
    entry_id: str
    verifier_evidence_json: str  # JSON-encoded evidence naming the verifier (Inv 17)
    verified_by: str
    verified_at_millis: int
    correlation_id: str
    schema_version: int = 1


class RetroRun(msgspec.Struct, frozen=True, kw_only=True):
    terminal_outcome_correlation_id: str
    source_task_id: str
    terminal_kind: str  # completed | rejected | aborted
    t0_matched_signatures: list[str]  # deterministic patterns matched (empty in B5.0 stub)
    llm_invoked: bool  # whether the LLM-for-residue path ran (False in B5.0 stub)
    candidates_emitted_count: int
    candidate_kinds: list[str]  # antibody_candidate | gate_change_candidate (empty in B5.0 stub)
    retro_run_at_millis: int
    correlation_id: str
    schema_version: int = 1
    # rev 0.4.24 additive: candidates the duplicate-candidate guard suppressed pre-emit (a
    # suppressed-only run is distinguishable from a genuinely-empty one)
    candidates_suppressed_count: int = 0


class OssWorktreeCreated(msgspec.Struct, frozen=True, kw_only=True):
    oss_task_id: str
    upstream_repo: str
    target_branch: str
    fork_branch: str
    worktree_path: str
    created_at_millis: int
    correlation_id: str
    schema_version: int = 1


class OssScopeBoundaryDerived(msgspec.Struct, frozen=True, kw_only=True):
    oss_task_id: str
    allowed_paths: list[str]  # the derived scope_boundary globs after OSS tightening
    derivation_basis: str  # e.g. "within_worktree" or "within_worktree + allowlist_intersection"
    derived_at_millis: int
    correlation_id: str
    schema_version: int = 1


class CommitIdentityAssigned(msgspec.Struct, frozen=True, kw_only=True):
    oss_task_id: str
    upstream_repo: str
    identity_name: str
    identity_email: str
    assigned_by: str
    commit_sha: str  # 40-char hex
    assigned_at_millis: int
    correlation_id: str
    schema_version: int = 1


class OssPrOpened(msgspec.Struct, frozen=True, kw_only=True):
    oss_task_id: str
    upstream_repo: str
    fork_branch: str
    base_branch: str
    pr_repo: str  # owner/repo the PR was opened against
    pr_number: int
    pr_url: str
    opened_at_millis: int
    correlation_id: str
    schema_version: int = 1


class CapRatificationRecommended(msgspec.Struct, frozen=True, kw_only=True):
    task_class: str
    samples: int
    observed_max: int
    current_cap: int
    recommended_cap: int
    action: str  # tighten | loosen | set
    recommended_at_millis: int
    correlation_id: str
    schema_version: int = 1


class ResourceSnapshot(msgspec.Struct, frozen=True, kw_only=True):
    """OS-resource accounting captured per task (devharness.health.system_snapshot). git_process_count
    is the fsmonitor-daemon leak signal; any failed probe is -1. The harness had event accounting but
    no resource accounting — this closes that gap so growth is visible on the dashboard."""
    process_count: int
    git_process_count: int
    worktree_count: int
    free_memory_mb: int
    captured_at_millis: int
    correlation_id: str
    schema_version: int = 1


class IntakeDecision(msgspec.Struct, frozen=True, kw_only=True):
    intake_correlation_id: str  # links the decision to its intake attempt
    decision: str  # accepted | rejected
    rejection_reason: str  # non-empty when decision == 'rejected'
    detected_patterns: list[str]  # injection pattern names (when decision rejected for injection)
    decision_at_millis: int
    correlation_id: str
    schema_version: int = 1

    def __post_init__(self):
        if self.decision == "rejected" and not self.rejection_reason:
            raise ValueError("IntakeDecision(rejected) requires a non-empty rejection_reason")


class MaintenanceTick(msgspec.Struct, frozen=True, kw_only=True):
    cycle_kind: str  # consolidate | prune | audit | synthesize
    tick_at_millis: int
    correlation_id: str
    schema_version: int = 1


class MaintenanceAction(msgspec.Struct, frozen=True, kw_only=True):
    cycle_kind: str  # consolidate | prune | audit | synthesize
    action_description: str
    evidence: dict
    correlation_id: str
    action_at_millis: int
    schema_version: int = 1

    def __post_init__(self):
        if not self.action_description:
            raise ValueError("MaintenanceAction requires a non-empty action_description")


class AdversarialTestRun(msgspec.Struct, frozen=True, kw_only=True):
    probe_name: str
    target_gate: str
    outcome: str  # expected_deny | regression_allow
    gate_check_reason: str
    correlation_id: str
    run_at_millis: int
    schema_version: int = 1


class GateRegressionDetected(msgspec.Struct, frozen=True, kw_only=True):
    probe_name: str
    gate_name: str
    unexpected_allow_reason: str
    correlation_id: str
    detected_at_millis: int
    schema_version: int = 1

    def __post_init__(self):
        if not self.unexpected_allow_reason:
            raise ValueError("GateRegressionDetected requires a non-empty unexpected_allow_reason")


class TrustGranted(msgspec.Struct, frozen=True, kw_only=True):
    role_name: str
    task_class: str
    brier_at_grant: float
    granted_at_millis: int
    expires_at_millis: int
    granted_by: str
    correlation_id: str
    schema_version: int = 1


class TrustGrantPruned(msgspec.Struct, frozen=True, kw_only=True):
    # An EXPIRED trust grant removed by an operator-authorized prune (the delete path complementing the
    # advisory PruneCycle — cycles never delete data, §S6). The handler deletes by ``grant_row_id`` (the
    # projection PK, reproducible on replay since proj_trust_grants avoids AUTOINCREMENT) — NOT the
    # natural key (role, class, granted_at), which is not unique (two grants can share a millisecond, one
    # later renewed, so a natural-key delete could drop a still-valid grant). role/class/granted_at stay
    # for the audit record. DELETE+replay reproduces the deletion (the prune event follows the grant in
    # the log). Requires pruned_by + reason (the authorization). Expired grants are already invalid at use.
    grant_row_id: int
    role_name: str
    task_class: str
    granted_at_millis: int
    pruned_by: str
    reason: str
    pruned_at_millis: int
    correlation_id: str
    schema_version: int = 1


class ProjectAssembled(msgspec.Struct, frozen=True, kw_only=True):
    # The operator assembled a built project: the final task's scratch branch was merged into the target
    # repo's main (the loop's terminal adopt step — previously a manual `git merge`). Audit-only, no
    # projection. plan_id/final_task_id identify the build; merge_sha is the resulting commit.
    plan_id: str
    final_task_id: str
    final_branch: str
    merge_sha: str
    target_path: str
    merged_into_branch: str
    correlation_id: str
    schema_version: int = 1


class CostSpent(msgspec.Struct, frozen=True, kw_only=True):
    # Realized LLM spend for one role's session/step (§S9; SC-6 as reworded at rev 0.3.60 — every
    # real spender emits, task_id populated whenever the spend is task-attributable). Emitted at role
    # run-end (developer/research/director/discovery own their accumulators), at dispatch-loop end
    # for the verifier+reviewer parallax clients (role="verify_review" — the T1 verifier client also
    # serves the non-goals check and persists across retry attempts; since rev 0.4.2 ONE emission per
    # DISTINCT client per dispatched task, each carrying ITS model — the prior single sum hid the
    # T1-verifier/frontier-reviewer split; the OSS loops and the standalone certify action emit it
    # too, task-scoped only when exactly one task ran), from the scope widener's cost_sink
    # (role="scope_resolver"), and role-scoped at run_maintenance ("retro_residue") and run_promote
    # ("promote"). Drives proj_cost (per-role cumulative spend), orphaned since B0.
    role: str
    amount_usd: float
    model: str = ""  # the model that billed this spend (rev 0.4.2; "" = pre-0.4.2 event)
    task_id: str = ""
    spent_at_millis: int = 0
    correlation_id: str = ""
    schema_version: int = 1


class BuildTargetSet(msgspec.Struct, frozen=True, kw_only=True):
    # The operator set the console's build target (the T action): where the developer builds and what
    # test command the verifier runs there. Audit-only, no projection; the console restores the latest
    # one on launch, so a restart doesn't force error-prone re-entry (a stale re-entered target once
    # landed an entire build in the WRONG project's repo). The event store is per-project, so restoring
    # the store's latest target is project-scoped.
    target_path: str
    test_command: list[str] = []
    correlation_id: str = "console"  # T normally precedes any research correlation
    schema_version: int = 1


class TrustRenewed(msgspec.Struct, frozen=True, kw_only=True):
    role_name: str
    task_class: str
    brier_at_renewal: float
    renewed_at_millis: int
    new_expires_at_millis: int
    renewed_by: str
    correlation_id: str
    schema_version: int = 1


class TrustRevoked(msgspec.Struct, frozen=True, kw_only=True):
    role_name: str
    task_class: str
    reason: str
    revoked_at_millis: int
    revoked_by: str
    correlation_id: str
    schema_version: int = 1

    def __post_init__(self):
        if not self.reason:
            raise ValueError("TrustRevoked requires a non-empty reason")


class TierFloorViolation(msgspec.Struct, frozen=True, kw_only=True):
    role: str
    task_class: str
    requested_tier: str
    required_tier: str
    correlation_id: str
    violated_at_millis: int
    schema_version: int = 1


class WorkItemCandidate(msgspec.Struct, frozen=True, kw_only=True):
    """A candidate work item a discovery run surfaced for a target repo (issue-discovery loop). The operator
    picks one — recorded as a question_answered whose answer_text is candidate_id — and promote drafts a spec
    from the chosen one. candidate_id is the stable id the operator picks by (e.g. "<corr>-w0")."""
    correlation_id: str
    candidate_id: str
    title: str
    description: str
    rationale: str
    kind: Literal["feature", "bugfix", "refactor", "test_gap", "dependency"]
    scope_hint: list[str]
    target_repo: str
    source: Literal["t0", "llm"]
    created_at_millis: int
    schema_version: int = 1

    def __post_init__(self):
        if not self.description:
            raise ValueError("WorkItemCandidate requires a non-empty description")


class InvariantViolated(msgspec.Struct, frozen=True, kw_only=True):
    """A behavioral invariant broke during a real build — emitted by the live invariant monitor
    (``devharness.monitor``), which sweeps the event log and flags a broken property the moment it can
    decide it. Audit-only (no projection): the panel + dashboard read these events directly. ``dedup_key``
    (invariant# + task_id + sorted offending event ids) makes a repeated sweep idempotent — the monitor
    skips a violation whose key already appears. The monitor never keys on this event type (no feedback
    loop). Turns the 18 invariants from test-time structural checks into live behavioral guards."""
    invariant_number: int
    property: str
    dedup_key: str
    offending_event_ids: list
    task_id: str = ""
    correlation_id: str = ""
    detail: str = ""
    detected_at_millis: int = 0
    schema_version: int = 1


class LoopFaultRun(msgspec.Struct, frozen=True, kw_only=True):
    """One loop-fault probe ran (feature B): a deliberate failure class was injected into a hermetic
    build and the live invariant monitor judged whether the harness coped. ``handled`` = the fault
    became one clean terminal, no violation; ``regression`` = the fault orphaned the task or produced a
    bad terminal (the sweep fired). Audit-only; the synthetic build lives in a throwaway store, only
    this result reaches the live log. Extends the adversarial self-tester from gates to the whole loop."""
    probe_name: str
    fault_class: str
    outcome: str  # handled | regression
    violation_count: int
    correlation_id: str
    run_at_millis: int
    schema_version: int = 1


class SignalRetroRun(msgspec.Struct, frozen=True, kw_only=True):
    """One signal-retro run (§S7 learning-loop closure): a monitor/fault-injection signal
    (``invariant_violated`` / ``fault_handling_regression``) the retro auditor processed into
    operator-review candidates. Doubles as the dedup ledger — a signal event whose ``signal_event_id`` has
    no ``proj_signal_retro_runs`` row is unprocessed (parallels ``retro_run`` for terminals). These two
    signals are unreachable by the terminal-triggered retro path, so a separate trigger drains them."""
    signal_event_id: str
    signal_event_type: str
    candidates_emitted_count: int
    candidate_kinds: list
    correlation_id: str
    run_at_millis: int
    schema_version: int = 1


class LoopFaultRegression(msgspec.Struct, frozen=True, kw_only=True):
    """A loop-fault probe caught a fault-handling REGRESSION (feature B): an injected failure that the
    harness should have turned into a clean terminal instead broke a behavioral invariant. Names the
    invariants that fired so the operator sees which guarantee regressed (e.g. Inv 10, a silent orphan)."""
    probe_name: str
    fault_class: str
    invariant_numbers: list
    detail: str
    correlation_id: str
    detected_at_millis: int
    schema_version: int = 1


EVENT_TYPES: dict[str, type] = {
    "connection_opened": ConnectionOpened,
    "role_transitioned": RoleTransitioned,
    "intent_proposed": IntentProposed,
    "gate_fired": GateFired,
    "verifier_outcome": VerifierOutcome,
    "checkpoint_taken": CheckpointTaken,
    "terminal_outcome": TerminalOutcome,
    "research_started": ResearchStarted,
    "question_asked": QuestionAsked,
    "question_answered": QuestionAnswered,
    "assumption_flagged": AssumptionFlagged,
    "spec_drafted": SpecDrafted,
    "spec_signed": SpecSigned,
    "explore_pass_completed": ExplorePassCompleted,
    "plan_drafted": PlanDrafted,
    "director_decision": DirectorDecision,
    "budget_exceeded": BudgetExceeded,
    "tier_floor_violation": TierFloorViolation,
    "write_lock_acquired": WriteLockAcquired,
    "write_lock_released": WriteLockReleased,
    "task_started": TaskStarted,
    "write_attempted": WriteAttempted,
    "write_applied": WriteApplied,
    "rewind_performed": RewindPerformed,
    "reviewer_certified": ReviewerCertified,
    "reviewer_rejected": ReviewerRejected,
    "task_dispatched": TaskDispatched,
    "trust_granted": TrustGranted,
    "trust_grant_pruned": TrustGrantPruned,
    "trust_renewed": TrustRenewed,
    "trust_revoked": TrustRevoked,
    "maintenance_tick": MaintenanceTick,
    "maintenance_action": MaintenanceAction,
    "adversarial_test_run": AdversarialTestRun,
    "gate_regression_detected": GateRegressionDetected,
    "oss_task_intake": OssTaskIntake,
    "intake_decision": IntakeDecision,
    "oss_worktree_created": OssWorktreeCreated,
    "oss_scope_boundary_derived": OssScopeBoundaryDerived,
    "commit_identity_assigned": CommitIdentityAssigned,
    "oss_pr_opened": OssPrOpened,
    "cap_ratification_recommended": CapRatificationRecommended,
    "resource_snapshot": ResourceSnapshot,
    "retro_run": RetroRun,
    "memory_entry_created": MemoryEntryCreated,
    "memory_entry_verified": MemoryEntryVerified,
    "antibody_candidate": AntibodyCandidate,
    "gate_change_candidate": GateChangeCandidate,
    "antibody_added": AntibodyAdded,
    "antibody_revoked": AntibodyRevoked,
    "candidate_rejected": CandidateRejected,
    "gate_change_rejected": GateChangeRejected,
    "candidate_reviewed": CandidateReviewed,
    "gate_change_enacted": GateChangeEnacted,
    "work_item_candidate": WorkItemCandidate,
    "project_assembled": ProjectAssembled,
    "build_target_set": BuildTargetSet,
    "cost_spent": CostSpent,
    "invariant_violated": InvariantViolated,
    "loop_fault_run": LoopFaultRun,
    "fault_handling_regression": LoopFaultRegression,
    "signal_retro_run": SignalRetroRun,
}
