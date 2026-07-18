"""Per-event projection handlers (one or more per projection-bearing event type in EVENT_TYPES).

Each handler updates its target projection table (spec §Data model). The
event->projection mapping was undefined in §Data model; the targets below are
the conventional choices made at B0.5 — three are direct (gate_fired,
verifier_outcome, terminal_outcome), three are flagged stand-ins:
  - connection_opened -> proj_role_state  (active role on connect; shares the
    singleton with role_transitioned, last-writer-wins by event_seq)
  - intent_proposed   -> proj_task_queue  (intent_id used as the queue key,
    call_class as task_class, state='proposed')
  - checkpoint_taken  -> proj_task_queue  (task state='checkpointed')
Five projections (proj_spec, proj_plan, proj_cost, proj_antibody_queue,
proj_gate_change_queue, proj_lock, proj_boot_parity) have no feeding event in the
7-event B0/B1 catalog and stay empty until their events exist.
"""

import json
import sqlite3

from devharness.projections.registry import ProjectionRegistry

PROJECTION_TABLES: list[str] = [
    "proj_role_state",
    "proj_spec",
    "proj_plan",  # redefined by 0004 (B1.6) as the real plan projection
    "proj_task_queue",
    # proj_review retired in 0013 (B3.0) — proj_verifier_outcomes is canonical
    "proj_gate_fires",
    "proj_cost",
    "proj_terminal_outcomes",
    "proj_antibody_queue",
    "proj_gate_change_queue",
    "proj_work_item_queue",  # 0027 issue-discovery candidate catalog
    "proj_lock",
    "proj_boot_parity",
    # B1.6 read-only-loop projections
    "proj_questions",
    "proj_assumptions",
    "proj_draft_spec",
    "proj_signed_spec",
    "proj_explore_summary",
    # B2.3 developer task-start
    "proj_task_started",
    # B2.4 checkpoints
    "proj_checkpoints",
    # B2.5 reviewer certifications
    "proj_reviewer_certs",
    # B2.6 task lifecycle
    "proj_task_lifecycle",
    # B2.7 task dispatch
    "proj_task_dispatched",
    # B2.8 calibrated-trust grants
    "proj_trust_grants",
    # B2.9 write-phase visibility
    "proj_developer_activity",
    "proj_verifier_outcomes",
    # B3.0 strict-sequential multi-task plan tracking
    "proj_plan_tasks",
    # B3.6 maintenance loop
    "proj_maintenance",
    # B3.7 adversarial self-tester
    "proj_adversarial",
    # B4.0 OSS-contribution intake
    "proj_oss_intake",
    # B4.1 intake-hardening decisions
    "proj_intake_decisions",
    # B4.4 OSS fork-branch worktrees
    "proj_oss_worktrees",
    # B4.5 OSS commit-identity split
    "proj_commit_identity",
    # B4.6 OSS budget overruns (proj_requester_cooldown is direct-written runtime state, NOT a projection)
    "proj_budget_exceeded",
    # B5.0 retro-trigger ledger
    "proj_retro_runs",
    # B5.2 antibody library
    "proj_antibody_library",
    # B5.5 federated cross-project memory
    "proj_memory",
    # gate-change enactment (the gate-change analogue of the antibody library)
    "proj_enacted_gate_changes",
    # 0028 signal-retro dedup ledger (invariant_violated / fault_handling_regression → candidates)
    "proj_signal_retro_runs",
]


def _developer_activity(conn, *, task_id, event_type, correlation_id, event_at_millis,
                        target_path=None, action_kind=None, predicted_success=None, observed_success=None,
                        task_class=None):
    conn.execute(
        "INSERT INTO proj_developer_activity (task_id, event_type, correlation_id, target_path, action_kind, "
        "predicted_success, observed_success, event_at_millis, task_class) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, event_type, correlation_id, target_path, action_kind, predicted_success, observed_success, event_at_millis, task_class),
    )


def _payload(event: dict) -> dict:
    return json.loads(event["payload"])


def handle_connection_opened(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_role_state (id, role, event_seq) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET role = excluded.role, event_seq = excluded.event_seq",
        (p["role"], event["seq"]),
    )


def handle_role_transitioned(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_role_state (id, role, event_seq) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET role = excluded.role, event_seq = excluded.event_seq",
        (p["to_role"], event["seq"]),
    )


def handle_intent_proposed(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_task_queue (task_id, task_class, state, event_seq) "
        "VALUES (?, ?, 'proposed', ?) "
        "ON CONFLICT(task_id) DO UPDATE SET task_class = excluded.task_class, "
        "state = excluded.state, event_seq = excluded.event_seq",
        (p["intent_id"], p["call_class"], event["seq"]),
    )


def handle_gate_fired(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_gate_fires (event_seq, gate, decision, reason, purpose, fix, correlation_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event["seq"], p["gate"], p["decision"], p["reason"], p["purpose"], p["fix"], event["correlation_id"]),
    )


def handle_verifier_outcome(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    # B3.0: the B0.5 proj_review stand-in is retired; proj_verifier_outcomes is canonical.
    conn.execute(
        "INSERT INTO proj_verifier_outcomes (task_id, verifier_name, outcome, evidence_json, correlation_id, outcome_at_millis) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (p["task_id"], p["verifier"], "pass" if p["passed"] else "fail",
         json.dumps(p.get("evidence", {})), event["correlation_id"], event["seq"]),
    )


def handle_checkpoint_taken(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    # B0.5 stand-in: mark the task checkpointed in the queue (retained)
    conn.execute(
        "INSERT INTO proj_task_queue (task_id, state, event_seq) VALUES (?, 'checkpointed', ?) "
        "ON CONFLICT(task_id) DO UPDATE SET state = excluded.state, event_seq = excluded.event_seq",
        (p["task_id"], event["seq"]),
    )
    # B2.4 real home: the checkpoint projection
    conn.execute(
        "INSERT INTO proj_checkpoints (checkpoint_id, task_id, worktree_path, git_commit_sha, "
        "correlation_id, taken_at_millis, rewound_at_millis) VALUES (?, ?, ?, ?, ?, ?, NULL) "
        "ON CONFLICT(checkpoint_id) DO UPDATE SET task_id = excluded.task_id, "
        "worktree_path = excluded.worktree_path, git_commit_sha = excluded.git_commit_sha, "
        "taken_at_millis = excluded.taken_at_millis",
        (
            p["checkpoint_id"], p["task_id"], p.get("worktree_path", ""), p.get("git_commit_sha", ""),
            event["correlation_id"], p.get("taken_at_millis", 0),
        ),
    )


def handle_rewind_performed(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "UPDATE proj_checkpoints SET rewound_at_millis = ? WHERE checkpoint_id = ?",
        (p["rewound_at_millis"], p["checkpoint_id"]),
    )


def handle_reviewer_certified(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_reviewer_certs (task_id, reviewer_session_id, verdict, reason, evidence_json, "
        "correlation_id, verdict_at_millis) VALUES (?, ?, 'certified', NULL, ?, ?, ?)",
        (p["task_id"], p["reviewer_session_id"], json.dumps(p.get("evidence", {})), event["correlation_id"], p["certified_at_millis"]),
    )


def handle_reviewer_rejected(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_reviewer_certs (task_id, reviewer_session_id, verdict, reason, evidence_json, "
        "correlation_id, verdict_at_millis) VALUES (?, ?, 'rejected', ?, ?, ?, ?)",
        (p["task_id"], p["reviewer_session_id"], p["reason"], json.dumps(p.get("evidence", {})), event["correlation_id"], p["rejected_at_millis"]),
    )


def handle_task_dispatched(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_task_dispatched (task_id, plan_id, dispatched_to_role, dispatched_by_role, "
        "correlation_id, dispatched_at_millis) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(task_id) DO UPDATE SET plan_id = excluded.plan_id, "
        "dispatched_to_role = excluded.dispatched_to_role, dispatched_by_role = excluded.dispatched_by_role, "
        "dispatched_at_millis = excluded.dispatched_at_millis",
        (p["task_id"], p["plan_id"], p["dispatched_to_role"], p["dispatched_by_role"], event["correlation_id"], p["dispatched_at_millis"]),
    )
    # B3.0: in-flight task pointer + per-task tracking (one task in flight at a time)
    conn.execute(
        "UPDATE proj_plan SET current_state = 'executing', executing_task_id = ?, current_task_id = ? WHERE plan_id = ?",
        (p["task_id"], p["task_id"], p["plan_id"]),
    )
    conn.execute(
        "INSERT INTO proj_plan_tasks (plan_id, task_id, task_state, task_class, dependency_task_ids, completed_at_millis) "
        "VALUES (?, ?, 'running', ?, ?, NULL) "
        "ON CONFLICT(task_id) DO UPDATE SET task_state = 'running', plan_id = excluded.plan_id, "
        "task_class = excluded.task_class, dependency_task_ids = excluded.dependency_task_ids",
        (p["plan_id"], p["task_id"], p.get("task_class", ""), p.get("dependency_task_ids", "")),
    )
    # B2.9 developer-activity feed
    _developer_activity(conn, task_id=p["task_id"], event_type="task_dispatched",
                        correlation_id=event["correlation_id"], event_at_millis=p["dispatched_at_millis"],
                        task_class=p.get("task_class"))


def handle_write_attempted(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    _developer_activity(
        conn, task_id=p["task_id"], event_type="write_attempted", correlation_id=event["correlation_id"],
        event_at_millis=p["attempted_at_millis"], target_path=p.get("target_path"), action_kind=p.get("action_kind"),
        predicted_success=p.get("predicted_success"), task_class=p.get("task_class"),
    )


def handle_write_applied(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    _developer_activity(
        conn, task_id=p["task_id"], event_type="write_applied", correlation_id=event["correlation_id"],
        event_at_millis=p["applied_at_millis"], target_path=p.get("target_path"), action_kind=p.get("action_kind"),
        observed_success=1 if p.get("observed_success", True) else 0, task_class=p.get("task_class"),
    )


def handle_oss_task_intake(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_oss_intake (upstream_repo, license_spdx, requester_id, target_branch, "
        "correlation_id, intake_at_millis) VALUES (?, ?, ?, ?, ?, ?)",
        (p["upstream_repo"], p["license_spdx"], p["requester_id"], p["target_branch"],
         event["correlation_id"], p["intake_at_millis"]),
    )


def handle_oss_worktree_created(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_oss_worktrees (oss_task_id, upstream_repo, target_branch, fork_branch, "
        "worktree_path, correlation_id, created_at_millis) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (p["oss_task_id"], p["upstream_repo"], p["target_branch"], p["fork_branch"],
         p["worktree_path"], event["correlation_id"], p["created_at_millis"]),
    )


_OSS_BUDGET_KINDS = {"oss_wall_clock", "oss_usd", "oss_requester_cooldown", "requester_revoked"}


def handle_budget_exceeded(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    # only OSS budget overruns project; B2.x per-role overruns (reasoning/token/wall_clock) stay
    # event-log-only (and would violate the proj_budget_exceeded CHECK).
    if p.get("budget_kind") not in _OSS_BUDGET_KINDS:
        return
    conn.execute(
        "INSERT INTO proj_budget_exceeded (budget_kind, limit_value, observed_value, action_taken, "
        "subject_id, reason, correlation_id, exceeded_at_millis) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (p["budget_kind"], p.get("limit_value"), p.get("observed_value"), p["action_taken"],
         p["subject_id"], p.get("reason") or None, event["correlation_id"], p["exceeded_at_millis"]),
    )


def handle_antibody_added(conn: sqlite3.Connection, event: dict) -> None:
    # B5.4: pure projection — inserts the library row only. The queue review transition is now driven by
    # candidate_reviewed (B5.2's antibody_added queue-flip was removed once review became explicit).
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_antibody_library (antibody_row_id, pattern_text, source_candidate_id, added_by, "
        "added_at_millis, correlation_id) VALUES (?, ?, ?, ?, ?, ?)",
        (p["antibody_row_id"], p["pattern_text"], p["source_candidate_id"], p["added_by"],
         p["added_at_millis"], event["correlation_id"]),
    )


def handle_cost_spent(conn: sqlite3.Connection, event: dict) -> None:
    # per-role cumulative spend (§S9; proj_cost was an unfed B0 placeholder until rev 0.3.56).
    # budget_usd stays NULL — per-role budgets were retired at constitution v0.2.0, and 0 would
    # misread as "a budget of $0". Replay-parity safe: pure accumulation from events; the upsert
    # preserves the first-insert rowid.
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_cost (role, spent_usd, budget_usd, event_seq) VALUES (?, ?, NULL, ?) "
        "ON CONFLICT(role) DO UPDATE SET spent_usd = spent_usd + excluded.spent_usd, "
        "event_seq = excluded.event_seq",
        (p["role"], p["amount_usd"], event["seq"]),
    )


def handle_gate_change_enacted(conn: sqlite3.Connection, event: dict) -> None:
    # pure projection — records the enacted gate-change into the running gate config (the gate-change
    # analogue of handle_antibody_added). change_details is re-serialized so the row is self-contained.
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_enacted_gate_changes (enacted_row_id, target_gate, change_kind, "
        "change_details_json, source_candidate_id, enacted_by, enacted_at_millis, correlation_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (p["enacted_row_id"], p["target_gate"], p["change_kind"], json.dumps(p.get("change_details", {})),
         p["source_candidate_id"], p["enacted_by"], p["enacted_at_millis"], event["correlation_id"]),
    )


def handle_candidate_reviewed(conn: sqlite3.Connection, event: dict) -> None:
    # B5.4: the operator-review transition — flips the candidate's queue row to approved/rejected and
    # records who reviewed it + when. Routes to the right queue by candidate_kind (parity-safe).
    p = _payload(event)
    if p["candidate_kind"] == "antibody_candidate":
        table, pk = "proj_antibody_queue", "antibody_row_id"
    else:
        table, pk = "proj_gate_change_queue", "gate_change_row_id"
    conn.execute(
        f"UPDATE {table} SET review_state = ?, reviewed_by = ?, reviewed_at_millis = ? WHERE {pk} = ?",
        (p["review_state"], p["reviewed_by"], p["reviewed_at_millis"], p["candidate_row_id"]),
    )


def handle_antibody_revoked(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "UPDATE proj_antibody_library SET revoked_at_millis = ?, revoke_reason = ? WHERE antibody_row_id = ?",
        (p["revoked_at_millis"], p["reason"], p["antibody_row_id"]),
    )


def handle_candidate_rejected(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    if p["candidate_kind"] == "antibody_candidate":
        conn.execute("UPDATE proj_antibody_queue SET review_state = 'rejected' WHERE antibody_row_id = ?", (p["candidate_row_id"],))
    else:
        conn.execute("UPDATE proj_gate_change_queue SET review_state = 'rejected' WHERE gate_change_row_id = ?", (p["candidate_row_id"],))


def handle_antibody_candidate(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_antibody_queue (retro_run_correlation_id, signature_name, pattern_text, "
        "evidence_event_ids, source, review_state, created_at_millis) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (p["retro_run_correlation_id"], p.get("signature_name") or None, p["pattern_text"],
         json.dumps(p.get("evidence_event_ids", [])), p["source"], p["created_at_millis"]),
    )


def handle_gate_change_candidate(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    cur = conn.execute(
        "INSERT INTO proj_gate_change_queue (retro_run_correlation_id, signature_name, target_gate, "
        "change_kind, change_details_json, evidence_event_ids, source, review_state, created_at_millis) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (p["retro_run_correlation_id"], p.get("signature_name") or None, p["target_gate"], p["change_kind"],
         json.dumps(p.get("change_details", {})), json.dumps(p.get("evidence_event_ids", [])),
         p["source"], p["created_at_millis"]),
    )
    # B5.3 (Inv 12): the validator runs in the persistence path — a core-gate-weakening candidate is
    # auto-rejected here, deterministically (parity-safe, covers every producer), before it can ever be
    # 'pending' for operator review. The gate_change_rejected AUDIT event (carrying auto_rejected) is
    # emitted separately by validate_gate_change_candidate; this durable state does not depend on it.
    from devharness.retro.gate_change_validator import would_weaken_core_gate
    if would_weaken_core_gate(p["target_gate"], p["change_kind"]):
        conn.execute("UPDATE proj_gate_change_queue SET review_state = 'rejected' WHERE gate_change_row_id = ?", (cur.lastrowid,))


def handle_work_item_candidate(conn: sqlite3.Connection, event: dict) -> None:
    # issue-discovery loop: catalog a discovered candidate work item into proj_work_item_queue. The operator
    # picks one via a question_answered carrying its candidate_id (no separate selection event).
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_work_item_queue (correlation_id, candidate_id, title, description, rationale, "
        "kind, scope_hint, target_repo, source, created_at_millis) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (p["correlation_id"], p["candidate_id"], p["title"], p["description"], p.get("rationale") or "",
         p["kind"], json.dumps(p.get("scope_hint", [])), p["target_repo"], p["source"], p["created_at_millis"]),
    )


def handle_memory_entry_created(conn: sqlite3.Connection, event: dict) -> None:
    # verified_locally=1 iff this project created the entry (source_project matches our identity);
    # an imported entry (foreign source_project) is untrusted (0) until verify_memory_entry (Inv 17).
    from devharness.memory.base import project_name
    p = _payload(event)
    local = 1 if p["source_project"] == project_name() else 0
    conn.execute(
        "INSERT OR IGNORE INTO proj_memory (entry_id, entry_type, entry_payload_json, source_project, "
        "verified_locally, created_at_millis, correlation_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (p["entry_id"], p["entry_type"], p["entry_payload_json"], p["source_project"], local,
         p["created_at_millis"], event["correlation_id"]),
    )


def handle_memory_entry_verified(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "UPDATE proj_memory SET verified_locally = 1, verified_at_millis = ?, verifier_evidence_json = ? "
        "WHERE entry_id = ?",
        (p["verified_at_millis"], p["verifier_evidence_json"], p["entry_id"]),
    )


def handle_retro_run(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_retro_runs (terminal_outcome_correlation_id, source_task_id, terminal_kind, "
        "t0_matched_signatures, llm_invoked, candidates_emitted_count, candidate_kinds, correlation_id, "
        "retro_run_at_millis) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (p["terminal_outcome_correlation_id"], p["source_task_id"], p["terminal_kind"],
         json.dumps(p.get("t0_matched_signatures", [])), 1 if p["llm_invoked"] else 0,
         p["candidates_emitted_count"], json.dumps(p.get("candidate_kinds", [])),
         event["correlation_id"], p["retro_run_at_millis"]),
    )


def handle_signal_retro_run(conn: sqlite3.Connection, event: dict) -> None:
    # §S7 learning-loop closure: record that a monitor/fault-injection signal event was processed into
    # operator-review candidates. The PK is the signal's own event_id (dedup: a signal already here is
    # never re-analyzed). INSERT OR IGNORE keeps a replay idempotent.
    p = _payload(event)
    conn.execute(
        "INSERT OR IGNORE INTO proj_signal_retro_runs (signal_event_id, signal_event_type, "
        "candidates_emitted_count, candidate_kinds, correlation_id, run_at_millis) VALUES (?, ?, ?, ?, ?, ?)",
        (p["signal_event_id"], p["signal_event_type"], p["candidates_emitted_count"],
         json.dumps(p.get("candidate_kinds", [])), event["correlation_id"], p["run_at_millis"]),
    )


def handle_commit_identity_assigned(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_commit_identity (oss_task_id, upstream_repo, identity_name, identity_email, "
        "assigned_by, commit_sha, correlation_id, assigned_at_millis) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (p["oss_task_id"], p["upstream_repo"], p["identity_name"], p["identity_email"],
         p["assigned_by"], p["commit_sha"], event["correlation_id"], p["assigned_at_millis"]),
    )


def handle_intake_decision(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_intake_decisions (intake_correlation_id, decision, rejection_reason, "
        "detected_patterns, correlation_id, decision_at_millis) VALUES (?, ?, ?, ?, ?, ?)",
        (p["intake_correlation_id"], p["decision"], p.get("rejection_reason") or None,
         json.dumps(p.get("detected_patterns", [])), event["correlation_id"], p["decision_at_millis"]),
    )


def handle_adversarial_test_run(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_adversarial (probe_name, target_gate, outcome, regression_reason, correlation_id, run_at_millis) "
        "VALUES (?, ?, ?, NULL, ?, ?)",
        (p["probe_name"], p["target_gate"], p["outcome"], event["correlation_id"], p["run_at_millis"]),
    )


def handle_gate_regression_detected(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    # attach the regression reason to the most recent adversarial run for this probe + correlation
    row = conn.execute(
        "SELECT adversarial_row_id FROM proj_adversarial WHERE probe_name = ? AND correlation_id = ? "
        "ORDER BY run_at_millis DESC, adversarial_row_id DESC LIMIT 1",
        (p["probe_name"], event["correlation_id"]),
    ).fetchone()
    if row is not None:
        conn.execute(
            "UPDATE proj_adversarial SET regression_reason = ? WHERE adversarial_row_id = ?",
            (p["unexpected_allow_reason"], row[0]),
        )


def handle_maintenance_tick(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_maintenance (cycle_kind, event_kind, action_description, correlation_id, event_at_millis) "
        "VALUES (?, 'tick', NULL, ?, ?)",
        (p["cycle_kind"], event["correlation_id"], p["tick_at_millis"]),
    )


def handle_maintenance_action(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_maintenance (cycle_kind, event_kind, action_description, correlation_id, event_at_millis) "
        "VALUES (?, 'action', ?, ?, ?)",
        (p["cycle_kind"], p["action_description"], event["correlation_id"], p["action_at_millis"]),
    )


def handle_trust_granted(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_trust_grants (role_name, task_class, brier_at_grant, granted_at_millis, "
        "expires_at_millis, revoked_at_millis, granted_by) VALUES (?, ?, ?, ?, ?, NULL, ?)",
        (p["role_name"], p["task_class"], p["brier_at_grant"], p["granted_at_millis"], p["expires_at_millis"], p["granted_by"]),
    )


def _active_grant_row(conn, role_name, task_class):
    return conn.execute(
        "SELECT grant_row_id FROM proj_trust_grants WHERE role_name = ? AND task_class = ? AND revoked_at_millis IS NULL "
        "ORDER BY granted_at_millis DESC, grant_row_id DESC LIMIT 1",
        (role_name, task_class),
    ).fetchone()


def handle_trust_grant_pruned(conn: sqlite3.Connection, event: dict) -> None:
    # the operator-authorized delete path: remove the grant row by its PRIMARY KEY (grant_row_id), not the
    # non-unique natural key — so a same-millisecond sibling grant is never collaterally deleted. A
    # DELETE+replay reproduces this (the prune event follows the trust_granted event in the log; the PK is
    # reproducible because proj_trust_grants avoids AUTOINCREMENT).
    p = _payload(event)
    conn.execute("DELETE FROM proj_trust_grants WHERE grant_row_id = ?", (p["grant_row_id"],))


def handle_trust_renewed(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    row = _active_grant_row(conn, p["role_name"], p["task_class"])
    if row is not None:
        conn.execute("UPDATE proj_trust_grants SET expires_at_millis = ? WHERE grant_row_id = ?", (p["new_expires_at_millis"], row[0]))


def handle_trust_revoked(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    row = _active_grant_row(conn, p["role_name"], p["task_class"])
    if row is not None:
        conn.execute("UPDATE proj_trust_grants SET revoked_at_millis = ? WHERE grant_row_id = ?", (p["revoked_at_millis"], row[0]))


# B0 terminal outcomes used completed|failed|abstained|aborted; B2.6 lifecycle terminals
# are completed|rejected|aborted. Map so proj_task_lifecycle.current_state stays CHECK-valid.
_TERMINAL_STATE_MAP = {
    "completed": "completed", "rejected": "rejected", "aborted": "aborted",
    "failed": "rejected", "abstained": "aborted",
}


def handle_terminal_outcome(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_terminal_outcomes (task_id, outcome, detail, event_seq) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(task_id) DO UPDATE SET outcome = excluded.outcome, "
        "detail = excluded.detail, event_seq = excluded.event_seq",
        (p["task_id"], p["outcome"], p["detail"], event["seq"]),
    )
    # B2.6: drive the lifecycle to its terminal state (no-op if the task never started)
    mapped = _TERMINAL_STATE_MAP.get(p["outcome"], "aborted")
    conn.execute(
        "UPDATE proj_task_lifecycle SET current_state = ?, terminal_at_millis = ?, outcome = ?, reason = ? "
        "WHERE task_id = ?",
        (mapped, p.get("terminated_at_millis", 0), p["outcome"], p.get("reason", ""), p["task_id"]),
    )
    # B3.0: record this task's terminal state (no-op if the task was never dispatched)
    terminated_at = p.get("terminated_at_millis", 0)
    conn.execute(
        "UPDATE proj_plan_tasks SET task_state = ?, completed_at_millis = ? WHERE task_id = ?",
        (mapped, terminated_at, p["task_id"]),
    )
    # B3.0: drive the dispatching plan's state — STRICT SEQUENTIAL completion. A plan reaches
    # 'completed' only when ALL its tasks have terminated 'completed'; any rejected/aborted task
    # blocks the plan (the director loop stops, so later tasks never dispatch). The lock serializes
    # execution, so exactly one task is in flight; current_task_id clears on each terminal.
    dispatched = conn.execute("SELECT plan_id FROM proj_task_dispatched WHERE task_id = ?", (p["task_id"],)).fetchone()
    if dispatched is not None:
        plan_id = dispatched[0]
        if mapped in ("rejected", "aborted"):
            plan_state = "blocked"
        else:
            completed = conn.execute(
                "SELECT count(*) FROM proj_plan_tasks WHERE plan_id = ? AND task_state = 'completed'", (plan_id,)
            ).fetchone()[0]
            total = conn.execute("SELECT task_count FROM proj_plan WHERE plan_id = ?", (plan_id,)).fetchone()
            plan_state = "completed" if (total is not None and total[0] is not None and completed >= total[0]) else "executing"
        conn.execute(
            "UPDATE proj_plan SET current_state = ?, last_terminal_at_millis = ?, executing_task_id = NULL, "
            "current_task_id = NULL WHERE plan_id = ?",
            (plan_state, terminated_at, plan_id),
        )


# --- B1.6 read-only-loop handlers ---
# spec_drafted/plan_drafted/explore_pass_completed derive their projection fields
# from the persisted artifact (the source of truth), which survives a rebuild.


def handle_question_asked(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_questions (correlation_id, research_id, question_id, question_text, asked_at_millis, answered) "
        "VALUES (?, ?, ?, ?, NULL, 0) "
        "ON CONFLICT(question_id) DO UPDATE SET correlation_id = excluded.correlation_id, "
        "research_id = excluded.research_id, question_text = excluded.question_text",
        (event["correlation_id"], p["research_id"], p["question_id"], p["question_text"]),
    )


def handle_question_answered(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "UPDATE proj_questions SET answered = 1, answer_text = ?, answered_at_millis = ? WHERE question_id = ?",
        (p["answer_text"], p["answered_at_millis"], p["question_id"]),
    )


def handle_assumption_flagged(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_assumptions (correlation_id, research_id, text, confidence, low_confidence_flag, flagged_at_millis) "
        "VALUES (?, ?, ?, ?, ?, NULL)",
        (event["correlation_id"], p["research_id"], p["text"], p["confidence"], 1 if p["low_confidence_flag"] else 0),
    )


def handle_spec_drafted(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    spec_id = p["spec_id"]
    row = conn.execute(
        "SELECT created_at_millis FROM artifacts WHERE artifact_id = ? AND artifact_type = 'spec'", (spec_id,)
    ).fetchone()
    drafted_at = row[0] if row else None
    conn.execute(
        "INSERT INTO proj_draft_spec (correlation_id, artifact_id, spec_id, signed, drafted_at_millis) "
        "VALUES (?, ?, ?, 0, ?) "
        "ON CONFLICT(spec_id) DO UPDATE SET correlation_id = excluded.correlation_id, "
        "artifact_id = excluded.artifact_id, drafted_at_millis = excluded.drafted_at_millis",
        (event["correlation_id"], spec_id, spec_id, drafted_at),
    )


def handle_spec_signed(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    spec_id = p["spec_id"]
    conn.execute(
        "INSERT INTO proj_signed_spec (correlation_id, artifact_id, spec_id, signed_by, signed_at_millis) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(spec_id) DO UPDATE SET signed_by = excluded.signed_by, signed_at_millis = excluded.signed_at_millis",
        (event["correlation_id"], spec_id, spec_id, p["signer"], p["signed_at_millis"]),
    )
    conn.execute("UPDATE proj_draft_spec SET signed = 1 WHERE spec_id = ?", (spec_id,))


def handle_plan_drafted(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    plan_id = p["plan_id"]
    row = conn.execute(
        "SELECT payload_json, created_at_millis FROM artifacts WHERE artifact_id = ? AND artifact_type = 'plan'", (plan_id,)
    ).fetchone()
    if row is not None:
        plan = json.loads(row[0])
        task_count = len(plan.get("tasks", []))
        spec_artifact_id = plan.get("spec_artifact_id")
        drafted_at = row[1]
    else:
        task_count = p.get("task_count")
        spec_artifact_id = p.get("spec_id")
        drafted_at = None
    conn.execute(
        "INSERT INTO proj_plan (correlation_id, plan_id, spec_artifact_id, task_count, drafted_at_millis) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(plan_id) DO UPDATE SET spec_artifact_id = excluded.spec_artifact_id, "
        "task_count = excluded.task_count, drafted_at_millis = excluded.drafted_at_millis",
        (event["correlation_id"], plan_id, spec_artifact_id, task_count, drafted_at),
    )


def handle_explore_pass_completed(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    explore_id = p["summary_ref"]
    row = conn.execute(
        "SELECT payload_json, created_at_millis FROM artifacts WHERE artifact_id = ? AND artifact_type = 'explore_pass'",
        (explore_id,),
    ).fetchone()
    if row is not None:
        art = json.loads(row[0])
        file_count = len(art.get("file_tree", []))
        manifest_count = len(art.get("dependency_manifests", []))
        test_count = len(art.get("test_signatures", []))
        ci_count = len(art.get("ci_configs", []))
        repo_root = art.get("repo_root")
        completed_at = row[1]
    else:
        file_count, manifest_count = p.get("file_count"), p.get("manifest_count")
        test_count, ci_count = p.get("test_count"), p.get("ci_count")
        repo_root = p.get("repo_path")
        completed_at = None
    conn.execute(
        "INSERT INTO proj_explore_summary (correlation_id, explore_pass_id, repo_root, file_count, manifest_count, "
        "test_count, ci_count, completed_at_millis) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(explore_pass_id) DO UPDATE SET repo_root = excluded.repo_root, file_count = excluded.file_count, "
        "manifest_count = excluded.manifest_count, test_count = excluded.test_count, ci_count = excluded.ci_count, "
        "completed_at_millis = excluded.completed_at_millis",
        (event["correlation_id"], explore_id, repo_root, file_count, manifest_count, test_count, ci_count, completed_at),
    )


# --- B2.0 single-writer lock handlers (proj_lock is now real, redefined by 0005) ---


def handle_write_lock_acquired(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_lock (lock_token, holder_role, correlation_id, acquired_at_millis) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(lock_token) DO NOTHING",
        (p["lock_token"], p["holder_role"], p["correlation_id"], p["acquired_at_millis"]),
    )


def handle_write_lock_released(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute("DELETE FROM proj_lock WHERE lock_token = ?", (p["lock_token"],))


def handle_task_started(conn: sqlite3.Connection, event: dict) -> None:
    p = _payload(event)
    conn.execute(
        "INSERT INTO proj_task_started (task_id, role, worktree_path, correlation_id, started_at_millis) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET role = excluded.role, "
        "worktree_path = excluded.worktree_path, started_at_millis = excluded.started_at_millis",
        (p["task_id"], p["role"], p["worktree_path"], event["correlation_id"], p["started_at_millis"]),
    )
    # B2.6: the task enters the lifecycle as running. On a RE-DRIVE the row still carries the prior
    # attempt's terminal fields — clear them, else the row is self-contradictory (current_state='running'
    # AND terminal_at_millis/outcome set), which made the AuditCycle (terminal_at_millis IS NULL = in-flight)
    # undercount a re-driven running task. Deterministic on replay (Inv 8 holds).
    conn.execute(
        "INSERT INTO proj_task_lifecycle (task_id, current_state, started_at_millis) VALUES (?, 'running', ?) "
        "ON CONFLICT(task_id) DO UPDATE SET current_state = 'running', started_at_millis = excluded.started_at_millis, "
        "terminal_at_millis = NULL, outcome = NULL, reason = NULL",
        (p["task_id"], p["started_at_millis"]),
    )
    # B2.9 developer-activity feed
    _developer_activity(conn, task_id=p["task_id"], event_type="task_started",
                        correlation_id=event["correlation_id"], event_at_millis=p["started_at_millis"])


HANDLERS = {
    "connection_opened": handle_connection_opened,
    "role_transitioned": handle_role_transitioned,
    "intent_proposed": handle_intent_proposed,
    "gate_fired": handle_gate_fired,
    "verifier_outcome": handle_verifier_outcome,
    "checkpoint_taken": handle_checkpoint_taken,
    "terminal_outcome": handle_terminal_outcome,
    "question_asked": handle_question_asked,
    "question_answered": handle_question_answered,
    "assumption_flagged": handle_assumption_flagged,
    "spec_drafted": handle_spec_drafted,
    "spec_signed": handle_spec_signed,
    "plan_drafted": handle_plan_drafted,
    "explore_pass_completed": handle_explore_pass_completed,
    "write_lock_acquired": handle_write_lock_acquired,
    "write_lock_released": handle_write_lock_released,
    "task_started": handle_task_started,
    "rewind_performed": handle_rewind_performed,
    "reviewer_certified": handle_reviewer_certified,
    "reviewer_rejected": handle_reviewer_rejected,
    "task_dispatched": handle_task_dispatched,
    "trust_granted": handle_trust_granted,
    "trust_grant_pruned": handle_trust_grant_pruned,
    "trust_renewed": handle_trust_renewed,
    "trust_revoked": handle_trust_revoked,
    "write_attempted": handle_write_attempted,
    "write_applied": handle_write_applied,
    "maintenance_tick": handle_maintenance_tick,
    "maintenance_action": handle_maintenance_action,
    "adversarial_test_run": handle_adversarial_test_run,
    "gate_regression_detected": handle_gate_regression_detected,
    "oss_task_intake": handle_oss_task_intake,
    "intake_decision": handle_intake_decision,
    "oss_worktree_created": handle_oss_worktree_created,
    # oss_scope_boundary_derived is event-log-only at B4.4 (no projection)
    "commit_identity_assigned": handle_commit_identity_assigned,
    "budget_exceeded": handle_budget_exceeded,
    "retro_run": handle_retro_run,
    "memory_entry_created": handle_memory_entry_created,
    "memory_entry_verified": handle_memory_entry_verified,
    "antibody_candidate": handle_antibody_candidate,
    "gate_change_candidate": handle_gate_change_candidate,
    "antibody_added": handle_antibody_added,
    "antibody_revoked": handle_antibody_revoked,
    "candidate_rejected": handle_candidate_rejected,
    "candidate_reviewed": handle_candidate_reviewed,
    "gate_change_enacted": handle_gate_change_enacted,
    "cost_spent": handle_cost_spent,
    "work_item_candidate": handle_work_item_candidate,
    "signal_retro_run": handle_signal_retro_run,
}


def register_handlers(registry: ProjectionRegistry) -> None:
    """Register the per-event_type projection handlers against their projection tables."""
    for table in PROJECTION_TABLES:
        registry.register_table(table)
    for event_type, handler in HANDLERS.items():
        registry.register_handler(event_type, handler)
