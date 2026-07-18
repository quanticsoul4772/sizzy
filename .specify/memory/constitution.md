# devharness Constitution

Version: 0.2.0
Status: Draft (stub)
Last updated: 2026-06-26

This constitution governs every design and implementation choice in devharness. It carries the ten standing principles from agent-harness-v2 forward and adds three commitments the multi-role shape forces.

When this document and the spec disagree, this document wins. When this document and code disagree, the document was wrong; amend the document, do not paper over with code.

Per Invariant 18 (rev 0.3 spec), each commitment declares a claim set of one or more boot-check function names. CI asserts that every commitment's declared set is present in the runtime boot-check registry and that every registered boot check is mapped back to a commitment. An unmapped commitment or an orphan boot check fails CI. Constitution amendments carry a semantic version bump.

**Stub status:** the boot-check names below are placeholders that ratify on the first B0 PR that wires the registry. They are deliberately specific so the parity gate has something to target; if a name proves wrong during B0 implementation, amend this file at the same time as the registry, never one without the other.

---

## Inherited principles (from agent-harness-v2)

### C1. Enforcement is structural.

Gates run in harness code, never as directives to the model. A model that ignores a prompt has not bypassed a gate; the gate runs anyway.

Boot-check claim set:
- `check_required_gates_registered`
- `workflow_guard`
- `secret_guard`
- `scope_guard`
- `sandbox`

### C2. Output-based health.

Health is tasks passing verification and diffs landing, not tokens emitted. A goal predicate must move before any action counts as success.

Boot-check claim set:
- `check_terminal_outcome_required_per_task`

### C3. Context has declared sources.

No role silently inherits another's history. `setting_sources=[]` posture: no auto-loaded CLAUDE.md /
settings in agent sessions. (The per-role *budget* claim was retired in v0.2.0 — the live cost model is
per-task caps + the director's per-task tier minima, not a per-role budget.)

Boot-check claim set:
- `check_setting_sources_empty`

### C4. The harness owns context reconstruction.

Each handoff context is assembled by the harness from the log and artifacts. The model never decides what the harness remembers.

Boot-check claim set:
- `check_handoff_context_assembled_by_harness`

### C5. Observability is structural.

The event log is the record; every action is an event with a correlation ID. No additive observability layer.

Boot-check claim set:
- `check_correlation_id_coverage`
- `check_event_log_writer_singleton`
- `check_projection_rebuild_parity`

### C6. Iteration rate × stakes drives complexity.

A one-line fix takes a short path; a high-stakes build gets the full loop. The router sits at the director (per Invariant 16).

Boot-check claim set:
- `check_director_iteration_router_present`

### C7. The dashboard is part of the harness.

It is how the operator holds the gates. Operator transparency is a load-bearing component, sibling to the event store and the gates.

Boot-check claim set:
- `check_dashboard_tile_coverage`

### C8. Layered falsification, failure as default.

Every output is wrong until a verifier proves it. Verifiers are deterministic, named in advance, and their decision rule is code.

Boot-check claim set:
- `check_verifier_attached_gate_registered`
- `check_verifier_decision_rule_is_code`

### C9. Every gate surfaces its purpose at enforcement.

Every deny carries `reason`, `purpose`, and `fix`. Operators never see a bare "blocked" without knowing what the gate was protecting and how to proceed.

Boot-check claim set:
- `check_gate_deny_envelope_shape`

### C10. Text responses are not engagement.

Tool calls are the unit of progress. Text without a tool call is not work.

Boot-check claim set:
- `check_tool_call_required_for_progress`

---

## Multi-role commitments (new in devharness)

### C11. One writer.

Only one agent edits code at a time; writes are never parallel. The single-writer lock governs developer-role code-mutating sessions (Invariant 1); worktrees are serial under the lock.

Boot-check claim set:
- `check_single_writer_lock_present`
- `check_concurrent_write_attempts_fail_closed`

### C12. The human owns the spec gate.

The state machine cannot enter BUILD from an unsigned spec. The operator's signature on the spec artifact is the gate.

Boot-check claim set:
- `check_spec_gate_present`
- `check_build_state_requires_signed_spec`

### C13. Handoffs are artifacts, not conversation.

Roles communicate through harness-validated documents (spec, plan, task, verdict), never free-form chat.

Boot-check claim set:
- `check_handoff_artifact_schema_registered`
- `check_handoff_artifact_validated_before_consumption`

---

## Amendment process

A constitution amendment is itself an event in the devharness event log (once B0 lands). Until B0, amendments are tracked in git history on this file. Every amendment requires:

- A written rationale in the commit body referencing the commitment changed.
- An updated `Version:` line at the top using semver (patch for clarification, minor for new commitment or new claim in a set, major for removal or contradiction of an existing commitment).
- For changes to a commitment's boot-check claim set, a matching change in the runtime boot-check registry must land in the same commit. Either-side-only changes fail Invariant 18 at CI and at boot.

---

## Amendment log

- **2026-06-26 v0.2.0 (retire the per-role-budget claim).** Removed `check_role_context_budget_declared` from C3's boot-check claim set (C3 drops from 2 to 1 name). The check was vacuous: it iterated a per-role spec registry (`roles/base.py:registered_roles`) that the real architecture never populates — roles grew their own `run()` loops instead of `spawn_role`/`RoleWorker`, and the live cost model is per-task caps (`oss/caps.py`) + the director's per-task tier minima, not a per-role budget. C3 is narrowed to "context has declared sources" (the `setting_sources=[]` posture, still enforced by `check_setting_sources_empty`). The dead `roles/base.py` substrate (`RoleSpec`/`spawn_role`/`RoleWorker`/the role registry) was deleted with it; `AgentRole`, `progress_from_messages`, and the `BudgetExceeded` exception (raised by the director's reasoning budget) are retained. **Total claim names: 24 → 23.** Minor bump per the amendment rule (a claim-set change; the commitment itself is narrowed, not removed). Inv-18 parity holds (registry == constitution claim set, both at 23).
- **2026-06-21 v0.1.1 (OSS gates → C1).** Added the four §S5 OSS fear-map gate names — `workflow_guard`, `secret_guard`, `scope_guard`, `sandbox` — to C1's boot-check claim set (C1 grows from 1 to 5 names), so Invariant 18's 1:N map covers them once the runtime registers the four gates. **Count correction:** the v0.1.0 entry stated "Total claim names: 19", but the enumerated claim sets actually sum to 20 (C5=3; C3/C8/C11/C12/C13 two each = 10; C1/C2/C4/C6/C7/C9/C10 one each = 7 → 20). Post-amendment total is therefore **24** (20 + 4). Version bumped to 0.1.1 per operator instruction (note: the amendment rule classifies "new claim in a set" as a minor bump, which would be 0.2.0 — followed the explicit instruction).
- **2026-06-20 v0.1.0 (initial draft stub).** Thirteen commitments authored from devharness-spec.md rev 0.3 §Governing Layer. Boot-check claim sets are placeholder names that the first B0 PR is expected to ratify against the actual registry. C5 declares three names (correlation ID, writer singleton, projection parity) because rev 0.2's review flagged it as 1:N rather than 1:1. C3, C8, C11, C12, C13 each declare two names. C1, C2, C4, C6, C7, C9, C10 declare one. Total claim names: 19.
