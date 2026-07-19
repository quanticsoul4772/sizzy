# devharness — Baseline Specification

**Status:** DRAFT rev 0.4.29 (B0–B5 all complete — the planned rollout is done; audit 18/0/0 full graduation)
**Owner:** operator
**Created:** 2026-06-18 · **Revised:** 2026-07-18 (rev 0.4.29)
**Codename:** `devharness`
**Constitution:** to be authored at `.specify/memory/constitution.md` from the thirteen commitments in §Governing Layer; versioned, with the parity gate in that section.

**Relationship to prior work:** New project. Not a fork or extension of any existing repo. It *consumes* parallax and mcp-reasoning as MCP servers and *reuses the architectural patterns* of agent-harness-v2 and pgharness with no shared code — the third instantiation of the v2 harness pattern for a new domain. The domain is general software development.

**Source material:**
- Internal corpus: agent-harness-v2, pgharness, v3-spec, bruno-swarm, sibling-agent, TradingAgents, parallax, mcp-reasoning
- External: Anthropic *Building Effective Agents* and the multi-agent research writeup; Cognition's single-writer posts; MetaGPT; OpenHands; SWE-agent; the MAST failure taxonomy (arXiv:2503.13657)

**Reading order:** Motivation → Scope → Resolved Decisions → Governing Layer → Architecture → Spine → Sub-systems → Invariants → Acceptance → Success Criteria → Assumptions → Rollout → Open Questions.

---

## Definitions

- **Cost tiers (T0–T3).** A routing ladder for where work runs by cost: **T0** deterministic/local, no LLM; **T1** cheap or local model (e.g. abliterated models via Ollama, per bruno-swarm); **T2** mid-tier API model; **T3** frontier API model. Advisory-intelligence roles bias toward T0–T1; the single writer runs at T2–T3.
- **call_class.** A classification applied to every tool call: `mutation` (changes state), `read`, or `harness` (internal control). The basis of calibration (§S1).
- **Advisory role / intelligence-contributor.** A role that informs a decision (research, reviewer, specialist advisors) but holds no code-write tools.
- **Orchestrator role.** The director: sequences work and decides forks via mcp-reasoning. No code-write tools. Distinct from advisory because its tier minimum is declared per task class (§S2), where advisory roles share the T0–T1 cap.

---

## Motivation

The harness exists because tool-wrapper integrations collapse the moment an agent has write authority on a codebase that matters. Cursor, Aider, Claude Code, OpenHands, and Devin are increasingly capable loops, but none is a *harness* in which the model is one gated component and the structure runs whether or not the model cooperates. None encodes the operator-loop properties a human developer relies on: blast-radius reasoning, reversibility, calibrated trust, verifier-first acceptance. pgharness made this argument for databases; devharness makes it for software development.

Three further facts shape the design:

1. **The work runs by hand today.** The operator already runs a research-with-the-human front-end (this chat), a director-style review step, and a writing step (a Claude Code session), ferrying context between them. devharness automates that loop while keeping the human at the gates that need judgment.

2. **The failure data is unambiguous.** Across 1,600+ multi-agent failure traces (MAST), ~42% of failures originate in specifications, ~37% in coordination and context loss, ~21% in shallow verification. Those three are precisely what the operator already has tools for: parallax `elicit` (specs), an event-sourced spine (coordination), parallax `verify` plus structural gates (verification).

3. **This is the project where multi-agent becomes the point.** agent-harness-v2, v3-spec, and pgharness all kept multi-agent orchestration as an explicit non-goal. devharness crosses that line — but only under the single-writer constraint (commitment 11), which keeps the coordination surface the size of a single-agent system even though the cast grew.

---

## Scope

**In scope:**
- A four-role loop: research, director, developer, reviewer.
- Single-writer enforcement (one agent edits code at a time).
- Event-sourced spine (append-only hash-chained log, rebuildable projections), three-process topology (Python runtime + Rust sidecar + Svelte dashboard, one SQLite file).
- Structured-artifact handoffs with a subscription model.
- Task-modes: new-project, existing-project, open-source-contribution; maintenance.
- The closed-loop learning spine with structural guarantees.
- Calibration and per-task-class trust.
- Cost model (API per-token primary + a narrow flat-cost escape) with per-task cap bounds.
- The thirteen-commitment governing layer with a constitution/enforcement parity gate.

**Out of scope (this baseline):**
- Parallel writers. Never two agents editing code at once. Non-negotiable.
- Full hands-off autonomy. The human owns the spec gate and, early on, integration.
- Multi-machine, multi-tenant, public SaaS, Kubernetes.
- A new observability layer. The event log is the telemetry.
- Forges other than GitHub for OSS mode at launch (see Assumptions — this makes `workflow_guard` GitHub-specific).
- Rewriting parallax or mcp-reasoning. They are consumed as-is over MCP.

**Non-scope (explicit):**
- Not a tool-wrapper. The model is a gated component, not the loop.
- Not a rewrite or fork of v2/pgharness/v3. Patterns are reused; code is not imported.
- Not a product. The sole user is the operator; downstream are the repos and PRs devharness produces.

---

## Resolved Decisions

Decisions committed at rev 0.2 that earlier drafts left open. Recorded here so the spec is internally consistent and the cost is explicit.

- **D1 — Four distinct roles (resolves former OQ2).** devharness commits to four roles with enforced boundaries (research, director, developer, reviewer), not a single writer-with-advisors. Rationale: the boundaries are only structural if they are separate capability surfaces; collapsing director and developer turns "the reviewer has no write tools" and "the director cannot touch a file" from invariants into prompt requests. **Accepted cost:** higher coordination and token cost than an advisors model. Mitigated by (a) routing advisory roles to T0–T1 (§S8), (b) the director reasoning budget bound (Invariant 16), and (c) the iteration-rate × stakes router (commitment 6) that lets small tasks bypass the full loop. Reversible only by an explicit operator decision before B0; reversing it re-opens roughly half the invariants.

---

## Governing Layer

devharness's constitution carries v2's ten commitments forward and adds three the multi-role shape forces. Each is a structure enforced in harness code, not a directive to the model. The constitution document is authored separately; this is the baseline it assumes.

1. **Enforcement is structural or it doesn't exist.**
2. **Output-based health.** Health is tasks passing verification and diffs landing, not tokens emitted.
3. **Context has declared sources.** No role silently inherits another's history; `setting_sources=[]`. (The per-role *budget* claim was retired in constitution v0.2.0 — the live cost model is per-task caps + the director's per-task tier minima, not a per-role budget.)
4. **The harness owns context reconstruction.** Each handoff context is assembled by the harness from the log and artifacts.
5. **Observability is structural, not additive.** The event log is the record; every action is an event with a correlation ID.
6. **Iteration rate × stakes drives complexity.** A one-line fix takes a short path; a high-stakes build gets the full loop. This router sits at the director (Invariant 16).
7. **The dashboard is part of the harness.** It is how the operator holds the gates.
8. **Layered falsification, failure as default.** Every output is wrong until a verifier proves it.
9. **Every gate surfaces its purpose at enforcement.** Every deny carries reason / purpose / fix.
10. **Text responses are not engagement.** Tool calls are the unit of progress.
11. **One writer.** Only one agent edits code at a time; writes are never parallel. (New.)
12. **The human owns the spec gate.** The state machine cannot enter BUILD from an unsigned spec. (New.)
13. **Handoffs are artifacts, not conversation.** Roles communicate through harness-validated documents, never free-form chat. (New.)

**Amendment and parity (drift gate).** The constitution is living and incident-driven; expect it to tighten as scars accumulate, as v3 tightened four of v2's ten after the hash-chain incident. To prevent the constitution silently drifting from the code that enforces it: an amendment requires a semantic version bump on the constitution document, and CI verifies a 1:N name-mapped binding (Invariant 18). Every commitment declares a claim set of one or more boot-check function names; every registered boot check maps back to a commitment; either side breaking fails CI.

---

## Architecture

Four roles, one writer. Each role is a capability surface defined by its enforced boundary — its identity *is* what it can and cannot do, not a personality in a prompt. (Role count committed in D1.)

### R1. Research agent (front of the line; human in the loop)

- **Boundary:** read and research tools only; no repo write tools.
- **Job:** turn a raw idea into a reviewed, self-contained spec artifact, with the operator. Breadth-first; may fan out parallel research sub-agents (the one place parallelization pays). Interviews the operator one question at a time; surfaces unstated assumptions; reports low-confidence points rather than inventing them.
- **Produces:** a spec artifact — problem, scope, non-goals, interfaces, success criteria, verification plan — plus an explicit assumptions-and-low-confidence section for the operator to resolve.
- **Reuses:** parallax `elicit`, `diverge`.

### R2. Director (orchestrator; sequences, never writes)

- **Boundary:** dispatch and planning tools; no file-write tools.
- **Job:** own the spec and plan as shared state; decompose into an ordered task list; dispatch one task at a time to the developer; integrate results; decide what's next; detect divergence from the plan and route back to research when the spec is wrong.
- **Reuses:** mcp-reasoning (`reasoning_decision` at forks, `reasoning_reflection` for self-critique before dispatch); bruno-swarm's architect role is the model, minus file-writing.
- **Constraints:** hands the developer a spec section and a scope boundary, not a line-by-line script (over-instruction is a documented manager failure mode). The director's per-task reasoning spend and model tier are bounded by task class and enforced at dispatch (Invariant 16); a task class declares a reasoning budget and a tier minimum (§S2), and the iteration-rate × stakes router (commitment 6) selects path depth and tier within those bounds so a one-line fix does not pay the full-loop tax.

### R3. Developer (the single writer)

- **Boundary:** holds the single write lock to one isolated worktree/sandbox; the only role with edit/write/commit tools; cannot write outside its task directory (kernel-enforced in OSS mode, filesystem-enforced otherwise).
- **Job:** execute one scoped task against its spec section, verifying as it goes.
- **Interface:** a designed Agent-Computer Interface (editor, shell, test-runner as structured actions) plus habit-scripts so repeated sequences are scripts, not ad-hoc shell. The ACI is an in-runtime MCP server (`devharness-aci`) the worker connects to alongside parallax and mcp-reasoning; its structured write actions replace raw `Edit`/`Write`/`Bash`, and every write is gate-checked (scope, blast-radius, destructive-command, verifier-attached) against the active task.
- **Form (OQ2 resolved, rev 0.3.7):** an **Agent SDK worker** — a runtime-driven subprocess with `setting_sources=[]`, tool inventory scoped via MCP servers, cwd set to its isolated worktree, per-call cost tracked by the runtime — mirroring the B1.0 advisory-role form factor. Resolved over a headless Claude Code session by a parallax `decide` (score 84 vs 42, confidence 0.71): the SDK-worker form gives the harness direct control of the tool boundary, the working directory, and per-call cost, which the single writer needs to enforce the lock and scope gates.

### R4. Reviewer / verifier (evaluator; adds intelligence, never writes)

- **Boundary:** no write tools at all; runs in a fresh context, not the session that wrote the code.
- **Job:** independently certify the developer's output against the spec and the verification plan. Layered, not superficial — compiling is not passing. Flags only what affects correctness or the stated requirements.
- **Reuses:** parallax `verify`, `check`, `grounded_verify`, plus the test suite.
- **Form (OQ5 resolved, rev 0.3.8):** **one Agent SDK worker subprocess per certification**, run in a fresh context (zero inherited history, `setting_sources=[]`), with a read-only tool inventory (parallax verify/check/grounded_verify + the ACI `run_tests`/read actions; no editor write actions, no shell `run_command`). A **single parallax-backed reviewer** producing one verdict — chosen over a bruno-swarm specialist panel by a parallax `decide` (score 78 vs 66, confidence 0.56). The specialist-panel pattern (security/test/quality advisors feeding one verdict) is **deferred and revisitable** if single-reviewer calibration later proves insufficient. **Default verifier set (rev 0.3.22, finding #2c).** The reviewer re-runs the task's acceptance criterion in fresh context, defaulting to `test_suite` — the universally-applicable independent re-verification (done earned twice, Inv 5). The claim-based parallax falsifiers (`parallax_verify`/`check`/`grounded_verify`, exported as `CLAIM_VERIFIERS`) are layered only for tasks that supply a genuine claim + verbatim sources; a `new_project_scaffold` cert supplies neither, so the prior fixed 4-set misfired (`parallax_grounded_verify` falsely rejecting on empty sources). Callers pass `verifiers=` for the claim-bearing path.
- **Note:** the reviewer (certification) is distinct from the declared verification (tests + parallax `verify`). A `completed` terminal requires both, separately (§S3).

### The loop

research (with operator) → spec → **operator sign-off gate** → director plans → developer writes one task in isolation → reviewer certifies → director integrates and advances → ship → maintain. Only the developer touches code. The human gate is at spec sign-off and, in early stages, at integration.

---

## The Spine

- **Event-sourced log as single source of truth.** Append-only, hash-chained; projections derived and rebuildable with a parity test. The audit trail, telemetry, and replay surface in one substrate.
- **Structured artifacts as handoffs, with a subscription model.** Roles read and write validated documents (spec, plan, task, verdict); each subscribes to what it needs. No free-form agent-to-agent chat.
- **Externalized, condensed context.** The director's plan lives in the log, not its window; sub-results return condensed.
- **Correlation IDs** on every message and tool call.
- **Cross-project memory.** Reusable scaffolds, patterns, and an anti-pattern library so project N+1 starts smarter than N. Voyage embeddings + memory layer, or parallax `save`/`recall`. A memory entry is `candidate` until promoted; promotion to `trusted` requires a verification event naming a verifier (Invariant 17). Staleness/downgrade policy is Open Question 4.

---

## Data model — event catalog and projection schemas

Authoritative as of rev 0.3.2. The runtime mirrors this section: event payloads in `runtime/devharness/events/registry.py`, projection tables in `schema/migrations/0002_projections.sql`. When this section and the runtime disagree, this section is the spec — amend it first.

### Event catalog (B0/B1 minimum)

Seven typed payloads. Each is a `msgspec.Struct(frozen=True, kw_only=True)` carrying `schema_version: int = 1`; payload evolution is a `schema_version` bump, never an in-place field rename. Field names are the conventional set chosen at rev 0.3.2.

```python
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
    call_class: str          # mutation | read | harness
    summary: str
    schema_version: int = 1

class GateFired(msgspec.Struct, frozen=True, kw_only=True):
    gate: str
    decision: str            # allow | deny
    reason: str
    purpose: str
    fix: str
    schema_version: int = 1

class VerifierOutcome(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    verifier: str
    passed: bool
    detail: str
    schema_version: int = 1

class CheckpointTaken(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    checkpoint_id: str
    ref: str
    schema_version: int = 1

class TerminalOutcome(msgspec.Struct, frozen=True, kw_only=True):
    task_id: str
    outcome: str             # completed | failed | abstained | aborted
    detail: str
    schema_version: int = 1
```

`gate_fired` carries `reason`/`purpose`/`fix` (commitment 9). `terminal_outcome` is the one-per-task terminal (Invariant 10). `intent_proposed.call_class` is the calibration basis (§S1).

### Projection schemas (the 12 dashboard tiles)

Each dashboard tile source (implementation-plan §6 / the §S9 surface) is a concrete projection table — a derived read model, rebuildable from the log (Invariant 8). `event_seq` on each row is the `events.seq` of the event that last wrote it.

**Surrogate keys avoid AUTOINCREMENT (rev 0.3.6).** A projection table with a surrogate row id uses a plain `INTEGER PRIMARY KEY` (a rowid alias), never `AUTOINCREMENT`. The Invariant 8 parity rebuild does `DELETE FROM <table>` then replays the log; a plain rowid restarts at 1 after a full delete, so the from-scratch replay reproduces the same surrogate ids the incremental path assigned. `AUTOINCREMENT` keeps a high-water mark in `sqlite_sequence` that survives the delete, so a rebuild would assign higher ids and parity would diverge. (Surfaced at B1.6 for `proj_assumptions`.) **Pre-production migration discipline:** a placeholder projection table that holds no data may be `DROP`+`CREATE`d in a later numbered migration to redefine it (B1.6 did this to replace the empty B0.4 `proj_plan` placeholder with the real plan projection). Once a table holds data, a redefinition must preserve it — `ALTER TABLE`, or a CTAS (`CREATE TABLE … AS SELECT …` + swap) pattern — never `DROP`+`CREATE`. Migrations stay forward-only and numbered either way.

```sql
CREATE TABLE proj_role_state (         -- tile 1: active role & FSM state
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    role      TEXT NOT NULL,
    event_seq INTEGER NOT NULL
);
CREATE TABLE proj_spec (               -- tile 2: current spec + sign-off
    spec_id   TEXT PRIMARY KEY,
    title     TEXT,
    signed    INTEGER NOT NULL DEFAULT 0,
    signed_at TIMESTAMP,
    event_seq INTEGER NOT NULL
);
CREATE TABLE proj_plan (               -- tile 3: current plan / task list
    task_id   TEXT PRIMARY KEY,
    ordinal   INTEGER NOT NULL,
    summary   TEXT,
    status    TEXT,
    event_seq INTEGER NOT NULL
);
CREATE TABLE proj_task_queue (         -- tile 4: task queue
    task_id    TEXT PRIMARY KEY,
    task_class TEXT,
    state      TEXT NOT NULL,
    event_seq  INTEGER NOT NULL
);
CREATE TABLE proj_review (             -- tile 5: diff under review
    task_id   TEXT PRIMARY KEY,
    diff_ref  TEXT,
    reviewer  TEXT,
    state     TEXT,
    event_seq INTEGER NOT NULL
);
CREATE TABLE proj_gate_fires (         -- tile 6: gate fires
    event_seq      INTEGER PRIMARY KEY,
    gate           TEXT NOT NULL,
    decision       TEXT NOT NULL,
    reason         TEXT,
    purpose        TEXT,
    fix            TEXT,
    correlation_id TEXT
);
CREATE TABLE proj_cost (               -- tile 7: per-role cost vs budget
    role       TEXT PRIMARY KEY,
    spent_usd  REAL NOT NULL DEFAULT 0,
    budget_usd REAL,
    event_seq  INTEGER NOT NULL
);
CREATE TABLE proj_terminal_outcomes (  -- tile 8: terminal outcomes
    task_id   TEXT PRIMARY KEY,
    outcome   TEXT NOT NULL,
    detail    TEXT,
    event_seq INTEGER NOT NULL
);
CREATE TABLE proj_antibody_queue (     -- tile 9: antibody candidates
    candidate_id TEXT PRIMARY KEY,
    summary      TEXT,
    status       TEXT NOT NULL,
    event_seq    INTEGER NOT NULL
);
CREATE TABLE proj_gate_change_queue (  -- tile 10: gate-change candidates
    candidate_id TEXT PRIMARY KEY,
    gate         TEXT,
    proposal     TEXT,
    status       TEXT NOT NULL,
    event_seq    INTEGER NOT NULL
);
CREATE TABLE proj_lock (               -- tile 11: single-writer lock holder
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    holder      TEXT,
    task_id     TEXT,
    acquired_at TIMESTAMP,
    event_seq   INTEGER NOT NULL
);
CREATE TABLE proj_boot_parity (        -- tile 12: boot-check / parity status
    check_name TEXT PRIMARY KEY,
    commitment TEXT NOT NULL,
    status     TEXT NOT NULL,
    event_seq  INTEGER
);
```

---

## Sub-systems

### S1. Calibration and trust

The principle: the developer earns write authority on a task class by demonstrated calibration, and abstention — kicking a task back as underspecified — is a rewarded output, not a failure.

- **`call_class` taxonomy** on every tool call: `mutation` | `read` | `harness`. The developer's prediction accuracy on `mutation` calls is the trust signal.
- **Metric/behavior alignment invariant:** the measured calibration metric and the behavior the role's prompt asks for MUST reference the same `call_class` set, derived from one source-of-truth constant (Invariant 14).
- **Per-task-class trust promotion:** write authority on a task class is granted/renewed/revoked on track record (grant/renew/revoke surface, per pgharness).
- **Calibrated abstention is valid:** low confidence routes the task back to research; this is the cheap, safe default.

**Implementation (B2.8).** Trust is event-sourced via `trust_granted` / `trust_renewed` / `trust_revoked`; `has_active_trust(role, task_class)` queries the `proj_trust_grants` projection (default 7-day expiry, env `DEVHARNESS_TRUST_EXPIRY_DAYS`). Invariant 8 rebuild parity holds for trust state — the same projection-of-events pattern as the B2.0 single-writer-lock projection. The calibration metric is the Brier score over the developer's `mutation`-call (predicted, observed) pairs; its mutation filter derives from the same `CALL_CLASSES` constant the role prompt enumerates (Invariant 14). SC-5 threshold ≤ 0.15 (ratified B2.8).

### S2. Task classes and gates

Each task class declares allowed operations, a scope, a director reasoning budget, and a director tier minimum; per-class gates run fail-closed. Initial classes, their dominant gate sensitivities, and director tier minimums:

| Task class | Dominant gate sensitivity | Director tier minimum |
|---|---|---|
| `new_project_scaffold` | blast-radius low, scope broad-but-greenfield | ≥T2 |
| `feature` | scope gate | ≥T2 |
| `bugfix` | scope gate, verifier-attached | ≥T1 |
| `refactor` | high scope-gate sensitivity (wide touch, behavior-preserving) | ≥T2 |
| `dependency_bump` | high blast-radius sensitivity | ≥T1 |
| ~~`oss_contribution`~~ | ~~the four OSS fear-map gates (§S5)~~ — **DEFERRED, not a class (rev 0.3.13)** | ≥T2 |
| `maintenance` | flat-cost permitted (§S8); idle-paced | ≥T0 |

The tier minimum is a per-class **cost dial**, and the tier→model router (rev 0.3.82) turns it into a real model choice: the high-complexity write classes (`new_project_scaffold`/`feature`/`refactor`) run the writer at ≥T2 (frontier), while the two low-complexity write classes — `bugfix` (a tight, targeted change) and `dependency_bump` (nearly mechanical) — floor at ≥T1, so **their writer runs on the cheaper T1 model** (operator decision, rev 0.3.84: a bump/bugfix write is low-risk enough to save on). `maintenance` (read-only) floors at T0. (Rev 0.3.83 briefly raised `bugfix`/`dependency_bump` to ≥T2 for uniformity; 0.3.84 restored ≥T1 per the operator's cost-vs-quality call — cheaper writes on the two mechanical classes.)

**OSS is an envelope, not a class (rev 0.3.13).** The `oss_contribution` row is **deferred** — B4 resolved (OQ-B4-2, parallax) to model an OSS contribution as an **`is_oss=True` BUILD task** (a `feature`/`bugfix`/`refactor`/`dependency_bump` against an external repo) rather than a standalone class. The four §S5 fear-map gates **layer additively** onto the BUILD class's gate profile when `is_oss=True`; the BUILD class's own verifier (B3) is reused unmodified; per-class Brier + trust keep keying on `(role, task_class)`. The §S5 envelope is a *safety* concern (gates, sandbox, intake, caps, identity), not a *verification* shape.

`refactor` and `dependency_bump` are first-class rather than folded under `maintenance` because their gate profiles differ materially. Tier minimums and per-class reasoning budgets are B1/B2-provisional pending calibration (OQ3). Gate families (modeled on pgharness's per-class registry):

- **Write-lock gate** — refuses a write when another role holds the lock.
- **Scope gate** — refuses edits outside the task's declared file/scope boundary.
- **Spec-signed gate** — refuses BUILD-class work without a signed spec artifact.
- **Verifier-attached gate** — refuses task start without a verification plan.
- **Blast-radius gate** — flags edits touching too many files or load-bearing paths (reasoning-required).
- **Destructive-command gate** — refuses force-push, history rewrite, state wipe.
- The four OSS fear-map gates (§S5) for `oss_contribution`.

### S3. Verifier-first acceptance

A task cannot be marked done until its declared verification passes: developer self-check → test suite → parallax `verify` → (early stages) operator integration gate. **A `completed` terminal requires two distinct things: (a) the declared verification passes, and (b) the reviewer (R4) certifies in a fresh context. They are separate checks; both are required.** The developer asserting "done" does nothing on its own. Evidence (the command and its result) is recorded, not asserted.

**Implementation (B2.2/B2.10).** `Verifier.verify` is `async` because parallax MCP calls are async. `run_verifier` is the sync↔async boundary and the supported entry point: it runs the verifier, emits `verifier_outcome`, and fires the auto-rewind hook on failure. Calling `verify()` directly outside the runner is discouraged — it bypasses the lifecycle wiring and the rewind path.

### S4. Checkpoint and rewind

Per-task checkpoint of worktree state; on verifier failure, rewind to the last good checkpoint. Each task runs in discardable isolation (git worktree or sandbox) so a bad task is reverted cleanly without touching others. **Isolation is not concurrency:** the single-writer lock (Invariant 1) governs code-mutating developer sessions, and worktrees are serial under that lock — never two active at once. Isolation buys clean rollback, not parallel writers.

**Implementation (B2.4/B2.6).** A checkpoint is a `git commit --allow-empty`; `rewind_to` is `git reset --hard <checkpoint>`. `rewind_to` takes a `clean` parameter (default `False`; `True` on auto-rewind after a verifier failure) — `clean=True` additionally runs `git clean -fd` so a rejected task leaves a fully-clean worktree with no untracked residue.

**Lock-release semantics (B2.7/B2.10).** The single-writer lock is held during the **write phase only**. The verify / review / terminal phases run **unlocked** because they are read-only and do not mutate code — functionally equivalent to "release after terminal" since the post-write phases never write. The current implementation releases the lock when `DeveloperRole.run()` returns (i.e. at the end of the write phase), after which the dispatch loop runs verification, certification, and the terminal disposition.

**OSS lock-held-through-verifier extension (rev 0.3.16).** For `is_oss=True` tasks the write phase is wider: the lock is held through **worker → verifier → (conditional) bot-identity commit**, all inside `DeveloperRole.run()`. The OSS verifier runs against the *uncommitted* worktree (so working-tree-stash verifiers — `bugfix_regression`, `refactor_behavior_preserving` — reach their baseline by stashing the developer's change), and the OSS identity commit (B4.5) lands **only if the verifier passes** (on failure `run_verifier` rewinds and emits the terminal — no commit). Rationale: an OSS commit on the fork-branch must be verifier-passed before it lands, in service of verifier-first acceptance (C2 done-is-earned) — the fork-branch never carries unverified commits. This narrows the non-OSS "verify runs unlocked" rule for OSS only: the OSS commit is a *write* and must be lock-held, and it must follow the verifier, so the verifier moves inside the locked session for OSS tasks. Reviewer certification + the terminal disposition still run unlocked, after `run()` returns. (Surfaced by the B4.8 acceptance, which found the prior ordering — commit before verify — both broke stash-baseline verifiers and committed unverified work.)

**Realized-diff scope enforcement (rev 0.3.21).** The developer's scope boundary is enforced on the **realized worktree diff**, not only on individual ACI editor tool-calls. A capable worker can write through the ACI shell (`run_command`, `shell=True`) or — under a permissive SDK permission posture — built-in tools, bypassing the per-write `scope_gate` and the `write_attempted`/`write_applied` tracking entirely (surfaced by the specledger first-project write step: a correct, test-passing scaffold landed with **zero** editor write events). Therefore, after `_run_worker` returns and before verifier acceptance, `DeveloperRole.run()` computes the set of paths changed in the worktree (`git status --porcelain -uall`, so `.gitignore` excludes build artifacts) and checks each against the task's `scope_boundary` (the same `fnmatch` rule the editor uses). Any changed path **outside** the boundary fails the task: the worktree is rewound `clean=True` and the director emits `terminal_outcome(rejected, reason="scope_violation:…")` directly (mirroring admission-deny), skipping verifier/review. In-scope realized writes the editor did not already emit are tracked with a `write_applied` (`action_kind="worktree_diff"`) so the projection layer sees shell/other-vector writes. Scope containment is thus **vector-independent within the worktree**: the editor stays the gated, per-write-tracked path, but the binding boundary is the realized diff. **OSS content gates on the realized diff (rev 0.3.25, #C1/#C2).** The §S5 `secret_guard` (content axis) and `scope_guard` (cumulative-LOC) read `context["diff_content"]`, which is empty at admission (the worker has not written yet) — so they passed vacuously on every real contribution. `DeveloperRole._enforce_content_gates` now runs them **in-lock, on the realized worktree diff** (`git diff` of the staged tree vs the checkpoint), for `is_oss` tasks (OSS-only: the LOC limit + the entropy axis would false-positive on legitimate local work). A deny rewinds `clean=True`, emits `gate_fired`, and the director rejects (`terminal_outcome(rejected, reason="secret_guard:…"/"scope_guard:…")`). These gates are now realized the same way scope_boundary is (rev 0.3.21) — on the actual diff, not on admission-time inputs that never carried one.

**Tool surface (rev 0.3.22).** The worker additionally runs with the built-in write/exec tools (`Bash`/`Write`/`Edit`/`MultiEdit`/`NotebookEdit`) in `disallowed_tools`, so the only write path is the ACI (gated editor or realized-diff-enforced shell) even under `bypassPermissions`; built-in read tools stay available. **Local-developer sandbox tier (rev 0.3.24, #1a).** The ACI shell (`run_command`) and test-runner (`run_tests`) route through a §S5 `SandboxLauncher` when the developer is given one (`DeveloperRole(sandbox_launcher=…)` — opt-in; default `None` = host execution). This is the **first wiring of `SandboxLauncher.exec` into command execution** — the launchers + the `sandbox` admission gate existed since B4.2.5 but only *gated on containment availability*, never routed commands. With a launcher set, shell/test commands run inside its isolation (WSL `unshare --user --net --pid --mount --uts` / VPS over SSH), so an out-of-worktree absolute-path write is contained where the realized-diff check cannot see it. **Residual (carried):** the launcher's filesystem-confinement depth (the WSL mount namespace still exposes `/mnt/c`; seccomp deferred) and the Windows↔WSL execution-environment mismatch mean routing alone does not yet fully confine the local Windows dev box — full confinement wants the worker to run end-to-end inside the Linux sandbox (as the OSS path intends). **Host execution is fail-closed (L4-1, rev 0.3.35).** When no launcher is set, the ACI shell/test-runner **refuse** to run on the host unless the operator explicitly authorizes it (`DEVHARNESS_ALLOW_HOST_SHELL=1` — a trusted-host opt-in, commitment 14). A host subprocess is not contained: the destructive-command blocklist (~11 substrings) + the realized-diff scope check stop force-push/history-rewrite and in-worktree file writes, but not arbitrary host reach (network exfil, reading host secrets, absolute-path writes). So the dangerous unsandboxed path is no longer the silent default — it is either sandboxed, or consciously authorized on a host the operator trusts, or refused (`HostExecutionRefused`).

### S5. OSS-contribution envelope (lifted from v3-spec, external-repo mode)

For `oss_contribution` tasks, all fail-closed and in REQUIRED_GATES from boot:

- **workflow_guard** — blocks writes to `.github/workflows/**`, `.github/actions/**` (override: approved-issue `allow_workflow_edit`). GitHub-specific by construction; a non-GitHub forge would need a forge-specific workflow-path gate (see Assumptions).
- **secret_guard** — **two independent axes (defense in depth, rev 0.3.14)**; either axis triggering denies, so a contributor must evade *both* to slip a secret past. (1) **Path axis** — blocks writes to secret-named files (`.env`, `.env.*`, `secrets.*`, `*.pem`, `*.key`, `id_rsa`/`id_dsa`/`id_ecdsa`/`id_ed25519`, `*.p12`, `*.pfx`, `*.keystore`, `credentials.*`, `.npmrc`, `.pypirc`, `*.kdbx`; extensible via `DEVHARNESS_SECRET_PATH_PATTERNS`, which *appends* to the defaults). (2) **Content axis** — scans the diff for secret-like patterns (AWS/GitHub/OpenAI keys, private-key headers, high-entropy strings). Each axis has its own override (`secret_guard_path_override` / `secret_guard_content_override`) so an operator can selectively allow one vector without disabling the other; both override marks are audited via `gate_fired`. Evidence carries the matched path list, pattern *names*, and a line count — never the matched secret text.
- **scope_guard** — blocks cumulative net LOC > 500, measured pre-write (override: `allow_large_change`).
- **sandbox** — blocks execution outside the process-level sandbox (PID/mount/network/user namespaces; netfilter egress allowlist; seccomp; read-only rootfs; secrets-as-mounted-files).
- **Intake hardening:** SPDX license allowlist check; maintainer verification; context-injection scan of the target repo's CONTRIBUTING/README/AGENTS/CLAUDE files before the agent touches anything.
- **Per-task caps:** wall-clock and USD ceilings; exceeding either aborts with a summary comment.
- **Requester cooldowns and revocation** on reverted merges.
- **Commit-identity split:** OSS commits carry a distinct bot identity, distinguishable from operator commits.

### S6. Maintenance loop (lifted from sibling-agent sleep stages)

For a shipped codebase devharness lives with: idle-time cycles that consolidate (what changed, what's learned), prune (stale knowledge, security audit), synthesize (cross-cutting connections), and surface work — paced by a fermata/graduated-pressure protocol so maintenance never interrupts active work abruptly. **The cycles are read-only** (the prune cycle *reports* what would be pruned; it never deletes) — actual removal is a separate, **operator-authorized** action (rev 0.3.33): `devharness prune` emits one `trust_grant_pruned` event per expired trust grant (an event-sourced delete — the projection row is removed and the deletion is reproduced on replay), requiring an explicit authorizer + reason. Only expired, non-revoked grants are touched (already invalid at point-of-use), so this is storage tidiness, never a correctness change.

### S7. Learning loop (lifted from v3-spec, with structural guarantees)

- Every task emits exactly one terminal outcome event; no task completes silently.
- Terminal outcomes feed a retro auditor on a schedule; retro output lands in a CANDIDATE stage for operator review and never auto-applies.
- **Antibodies are text only**, never code. A retro output that proposes code is routed to a separate gate-change queue.
- **Proposed gate changes require an explicit, distinct operator label transition**, enforced by projection code.
- **An approved gate change is enacted when it is auto-applicable** (rev 0.3.33; scoped rev 0.3.34): the additive `add_signature` kind is enacted into `proj_enacted_gate_changes` via the `gate_change_enacted` event (the only path from approved to in-effect, mirroring `antibody_added`) and gates consult it live (the `antibody_screen` gate screens enacted `add_signature` patterns). A core-gate weakening can **never** be enacted (Inv 12). The deterministic spine's `tighten`/`loosen` signals (on `verifier_attached_gate` — binary, no tunable threshold — and `cost_mode_gate` — allowed modes are structural per-class config) have no auto-applicable parameter; they are approved as operator decisions (`candidate_reviewed`) but the OPERATOR applies them — auto-mutating enforcement from a retro signal is out of scope. So `proj_enacted_gate_changes` holds only what is actually in effect, never an inert row.
- **Core gates cannot be weakened by a retro proposal** — rejected at the validator and logged.
- **Hostile input is quarantined** before it can reach a retro prompt.
- Eval discipline (TradingAgents): experiment-per-change, the T0–T3 cost ladder (see Definitions), shadow-before-default for new gates, retrospective-before-spec, a living constitution amended per finding (under the parity gate).

### S8. Cost model (lifted from v3-spec)

API per-token primary, with a narrow flat-cost escape via a `session.cost_mode` field on the task record, enforced in a task-class × cost-mode gate. Flat-cost permitted only for `maintenance` and consolidation classes; per-token forced for any class with write authority. The distinction is a thin boundary: `cost_mode ==` comparisons confined to two modules, CI-enforced (Invariant 13). Layer the T0–T3 ladder on top (see Definitions); route advisory-intelligence roles to T0–T1 while the single writer runs at T2–T3. The director sits in its own orchestrator tier: each task class declares a reasoning budget and a tier minimum in §S2, and the iteration-rate × stakes router (commitment 6) selects within those bounds so the orchestrator does not become a per-task tax (Invariant 16). Budget ~15x a chat interaction as the floor for the full loop.

### S9. Dashboard

Live operator surface: active role, current spec and plan, task queue, diff under review, gate fires, cost (including per-role spend against budget), terminal outcomes, learning-candidate review queues. Polling slows when paused. The original 12 tiles' backing projection tables are defined in §Data model — event catalog and projection schemas; B1 expands the surface to 18 tiles, B2 to 23, B3 to 25, and B4 to **28 tiles** (below).

**SSE delivery (rev 0.3.4).** The Rust sidecar serves the event log as per-channel Server-Sent Events (`/events/all` plus a per-event-type endpoint) and carries a permissive `tower-http` CORS layer so a browser dashboard served from a different origin can open `EventSource` streams; without it cross-origin SSE is blocked by the browser.

**Dashboard SSE multiplexing (rev 0.3.4).** The dashboard's 12 tiles share a single `EventSource` to `/events/all` and demultiplex events client-side by `event_type`. Per-tile EventSource connections are forbidden: the browser's HTTP/1.1 limit of ~6 concurrent connections per host starves any tile beyond the sixth (observed in the B0.8 acceptance render, where the 7th stream never opened).

**Research-flow tiles (rev 0.3.5).** B1 adds six tiles (12 → 18), each fed by a B1 event type over the shared `/events/all` multiplex: **questions** (← `question_asked`), **assumptions** (← `assumption_flagged`), **draft spec** (← `spec_drafted`), **signed spec** (← `spec_signed`), **plan** (← `plan_drafted`), **explore summary** (← `explore_pass_completed`). The seven existing unwired-placeholder tiles remain until their feeding events come online in later phases.

**Write-phase tiles (rev 0.3.9).** B2 adds five tiles (18 → 23) for write-phase visibility, each over the shared `/events/all` multiplex: **developer_activity** (← `task_started`, `task_dispatched`, `write_attempted`, `write_applied`), **verifier_outcomes** (← `verifier_outcome`), **reviewer_certs** (← `reviewer_certified`, `reviewer_rejected`), **lock_checkpoint** (← `write_lock_acquired`, `write_lock_released`, `checkpoint_taken`, `rewind_performed`), **trust_state** (← `trust_granted`, `trust_renewed`, `trust_revoked`).

**Maintenance/adversarial tiles (rev 0.3.11).** B3 adds two tiles (23 → 25), each over the shared `/events/all` multiplex: **maintenance** (← `maintenance_tick`, `maintenance_action`, per the §S6 maintenance loop), **adversarial** (← `adversarial_test_run`, `gate_regression_detected`, per the adversarial self-tester) — the latter surfaces a gate regression to the operator immediately.

**OSS-envelope tiles (rev 0.3.15).** B4 adds three tiles (25 → 28), each over the shared `/events/all` multiplex: **oss_intake** (← `oss_task_intake`, `intake_decision`; groups accepted vs rejected and surfaces the rejection_reason), **oss_enforcement** (← `budget_exceeded` filtered to the OSS `budget_kind` variants — `oss_wall_clock`/`oss_usd`/`oss_requester_cooldown`/`requester_revoked`; surfaces the `action_taken` and revocations prominently), **oss_branch** (← `oss_worktree_created`, `commit_identity_assigned`; the fork-branch lifecycle from worktree creation to commit-identity assignment).

**Tile manifest (C7, rev 0.3.87).** The dashboard renders exactly these 28 tiles. The C7 boot-check (`check_dashboard_tile_coverage`) parses this list against `dashboard/src/tiles/registry.js`; divergence either way fails closed. (rev 0.3.87 added `invariant_monitor` — the live invariant monitor's `invariant_violated` breaches, 27→28. rev 0.3.81 added `cost` — per-role LLM spend, `cost_spent`→`proj_cost` finally surfaced, 26→27. rev 0.3.32 added `resource_health` — per-task OS-resource accounting via the `resource_snapshot` event, 25→26. rev 0.3.31 removed 7 feedless B0 generic projection placeholders — `proj_spec`/`proj_plan`/`proj_cost`/`proj_antibody_queue`/`proj_gate_change_queue`/`proj_lock`/`proj_boot_parity` — which had no feeding event, rendered a permanent "no live event feed", and duplicated dedicated named tiles that superseded them; 32→25. The projection tables themselves remain in §Data model.)
- `proj_role_state`
- `proj_task_queue`
- `proj_review`
- `proj_gate_fires`
- `proj_terminal_outcomes`
- `questions`
- `assumptions`
- `draft_spec`
- `signed_spec`
- `plans`
- `explore_summary`
- `developer_activity`
- `verifier_outcomes`
- `reviewer_certs`
- `lock_checkpoint`
- `trust_state`
- `maintenance`
- `adversarial`
- `oss_intake`
- `oss_enforcement`
- `oss_branch`
- `candidate_queue`
- `antibody_library`
- `retro_activity`
- `trusted_memory`
- `resource_health`
- `cost`
- `invariant_monitor`

**Events-as-SSE payload denormalization (rev 0.3.6).** The dashboard renders strictly from the SSE event stream — it never queries projection tables. So a tile can only show what its feeding event's payload carries. When a tile needs a field whose source-of-truth lives in a persisted artifact (the server-side projection reads it from there), that field is *also denormalized into the event payload* so the client can render it. B1.6 surfaced two cases: `SpecSigned` gained `signed_at_millis` (so the signed-spec tile shows the sign time, and `proj_signed_spec.signed_at_millis` is filled from the event), and `ExplorePassCompleted` gained `file_count`/`manifest_count`/`test_count`/`ci_count` (so the explore-summary tile shows counts the projection otherwise derives from the persisted `ExplorePassArtifact`). The projection handlers still derive these from the artifact (the authority); the event copy exists for the event-driven client. This is the standing rule: if the dashboard must show it, it goes in the event payload, even when an artifact also holds it.

---

## Invariants (each MUST have a test)

1. **Single-writer lock.** No two roles hold the write lock simultaneously; a second write attempt fails closed. The lock governs code-mutating developer sessions; worktrees are serial under it (§S4), never parallel.
2. **Reviewer has no write tools.** The reviewer role's tool set contains zero write/edit/commit tools.
3. **Director has no file tools.** The director can dispatch but cannot write files.
4. **Spec gate.** The state machine cannot transition to BUILD without a signed spec artifact present.
5. **Done is earned.** A task cannot reach a `completed` terminal without (a) its declared verification passing and (b) reviewer certification — both, separately (§S3).
6. **Handoffs are schema-validated.** Every artifact consumed by a downstream role validates against its schema; an invalid artifact is rejected, not consumed.
7. **Event log append-only + hash-chained.** Manual mutation that breaks the chain fails the boot integrity check.
8. **Projection rebuild parity.** Replaying the full event log reproduces incremental projection state.
9. **Correlation coverage.** Every message and tool-call event carries a correlation ID.
10. **No silent termination.** Every task that reaches `running` emits exactly one terminal outcome event.
11. **Antibodies are text only.** A retro output that proposes code never enters the antibody queue.
12. **Core gates unweakable by retro.** A retro proposal to weaken a core gate is rejected at the validator and logged.
13. **Cost-mode branching confined.** `cost_mode ==` comparisons appear only in the two whitelisted modules.
14. **Calibration alignment.** A unit test asserts that the calibration SQL's `WHERE call_class IN (...)` set and the role prompt's enumerated `call_class` set are both derived from a single source-of-truth constant; divergence fails CI.
15. **REQUIRED_GATES boot check.** Missing any required gate (including the four OSS fear-map gates) fails boot.
16. **Director reasoning budget and tier bounded.** Each task class declares a director per-task reasoning budget and a tier minimum (§S2); the director's spend on a task is capped at dispatch by its class budget, and the model selected sits at or above the class tier minimum. Exceeding the budget halts the task and emits a `director.budget_exceeded` event rather than overrunning silently. Dispatch to a model below the tier minimum is refused with a `director.tier_floor_violation` event.
17. **Trusted memory is verified.** A cross-project memory entry promoted from `candidate` to `trusted` carries a verification event naming the verifier that cleared it; an unverified entry cannot reach `trusted`.
18. **Constitution/enforcement parity (1:N name-mapped).** Each commitment in the constitution declares a claim set of one or more boot-check function names; CI asserts that every commitment's declared set is present in the runtime boot-check registry and that every registered boot check is mapped back to a commitment. An unmapped commitment or an orphan boot check fails CI. Constitution amendments carry a semantic version bump.

---

## Acceptance (by audience)

### Operator

- **A-OP-1.** The operator initiates a new-project build; research produces a spec artifact with an explicit assumptions section; the build does not enter BUILD until the operator signs off. The dashboard shows role transitions in real time.
- **A-OP-2.** A developer task that attempts to edit outside its scope boundary is denied with a reason/purpose/fix message; the deny appears in the dashboard.
- **A-OP-3.** A retro run produces antibody and gate-change candidates; both appear in distinct operator-review queues; no auto-apply occurs.
- **A-OP-4.** Booting with any required gate missing fails boot with a deny naming the gate.

### Internal roles + subsystems

- **A-SYS-1.** A second concurrent write attempt fails the single-writer lock (Invariant 1).
- **A-SYS-2.** The reviewer cannot write code: a synthetic write attempt from the reviewer role has no tool to call (Invariant 2).
- **A-SYS-3.** A task marked done by the developer without a passing verification and a reviewer certification stays non-terminal (Invariant 5).
- **A-SYS-4.** Every task reaching `running` has exactly one terminal event in a 7-day audit (Invariant 10).
- **A-SYS-5.** A synthetic retro proposal to weaken a core gate is rejected at the validator (Invariant 12).
- **A-SYS-6.** A director task that would exceed its class reasoning budget halts with `director.budget_exceeded` (Invariant 16).

### Observable in downstream repos

- **A-EXT-1.** Every OSS PR commit carries the bot identity, distinguishable from operator commits.
- **A-EXT-2.** No OSS PR exceeds 500 net LOC without `allow_large_change`.
- **A-EXT-3.** No OSS PR modifies workflow files without `allow_workflow_edit`.
- **A-EXT-4.** An OSS task that launches outside the sandbox fails the task (and boot if the gate is absent).

---

## Success criteria (measurable)

- **SC-1.** 100% of builds emit a terminal outcome event; a 7-day audit reports zero orphans.
- **SC-2.** 0 retro-produced code changes reach the runtime without an explicit operator label transition.
- **SC-3.** 100% of `oss_contribution` tasks run inside the sandbox; an out-of-sandbox launch fails, not just warns.
- **SC-4.** Single-writer lock violations: 0 in production.
- **SC-5.** Developer calibration on `mutation` calls reaches **Brier score ≤ 0.15** on the `call_class`-filtered metric within 30 days of the first write-authority stage, with the prompt and SQL sharing one classifier. (Threshold ratified against the B2 baseline; treat as B2-provisional until then.)
- **SC-6.** Every real (per-token) LLM spend is recorded as a `cost_spent` event **carrying the model that billed it** (`model`, rev 0.4.2 — tier routing is ledger-verifiable, not only code-verifiable): task-scoped (`task_id` populated) for every task-attributable spender (the developer's worker session, the dispatch loop's verifier+reviewer clients — **one emission per distinct client**, since a summed emission would hide the T1-verifier/frontier-reviewer split — the standalone certify action's reviewer client, the scope widener), role-scoped otherwise (research/director/discovery/retro-residue/promote; a multi-task OSS loop's shared clients omit `task_id` rather than fabricate attribution). A zero-spend run emits nothing, so a task terminating with no recorded cost is by construction a no-LLM (mocked) run. *(Reworded at rev 0.3.60 — the original `cost.tick` name predated the implemented event and matches no registry convention (all event types are snake_case), and its flat-cost half is vacuous until a flat-cost class ever emits task terminals: maintenance emits window/cycle events, never task terminals. If one ever does, a zero-USD `cost_spent` realizes the intent.)*
- **SC-7.** Dashboard SQL has 100% schema-compat CI coverage at launch (L7 lesson).
- **SC-8.** Reviewer certification precedes every `completed` terminal in a 7-day audit (the certification half of Invariant 5).
- **SC-9.** Director per-task reasoning cost stays within its class budget; budget-exceed halts, not overruns: 0 silent overruns in production.
- **SC-10.** Every constitution commitment's declared boot-check claim set is present in the runtime registry, and every registered boot check is mapped to a commitment (Invariant 18, 1:N name-mapped); CI green, 0 drift.

---

## Assumptions

- Single operator, single machine (managed VPS), as with v2/pgharness. Multi-machine is a future substrate swap, not a shipping shape.
- SQLite + WAL + FTS5 + sqlite-vec is the state substrate.
- The Claude Agent SDK (Python) is the runtime's client; the developer runs as a headless Claude Code session or SDK worker.
- **GitHub is the forge for OSS mode.** This makes `workflow_guard` GitHub-specific (it pins `.github/workflows/**`); the gate is not forge-agnostic, and a future forge would require its own workflow-path gate.
- parallax and mcp-reasoning are reachable as MCP servers and are not modified by this project.
- The operator is the sole reviewer of candidates and sole holder of the spec-sign-off gate.

---

## Implementation sequencing (rollout)

Phased write-authority ramp (pgharness) with a boot check at every cut line and rollback at any boundary; the event log is never rewritten across cut lines.

- **B0 — substrate.** Event log + projections + parity test; the three-process skeleton; dashboard with live tiles; the thirteen commitments encoded as boot checks with the 1:N name-mapped parity gate (Invariant 18), shipping with the enumerated commitment-to-boot-check map as its baseline; adopt-from-birth lessons L7–L11. No agent behavior. **D1 (four-role) must be settled before B0 begins.**
- **B1 — read-only loop.** Research front-end (parallax `elicit`/`research`/`diverge`) producing a spec artifact with an assumptions section; director that plans but cannot dispatch writes, with the per-class reasoning budget wired; explore-pass for existing repos. Everything read-only. The "research → signed spec" cut line.
- **B2 — first scoped write authority.** Developer gets the single write lock on `new_project_scaffold`, behind verifier-first acceptance (tests + parallax `verify`) and reviewer certification, reviewer in fresh context, checkpoint + rewind, calibrated-trust promotion. Ratify the SC-5 calibration threshold here. The "devharness can write" cut line.
- **B3 — widen the modes. ✅ COMPLETE (closed at `975d7b7`).** `feature`, `bugfix`, `refactor`, `dependency_bump` on existing repos (with the explore-pass), each with its own verifier; the maintenance loop (§S6, fermata-paced, flat-cost class); adversarial self-tester probing the gates on a cadence in the maintenance window. All ten sub-phases B3.0–B3.9 landed CI-green; the four-class strict-sequential multi-task loop is verified end-to-end.
- **B4 — OSS contribution. ✅ COMPLETE (closed at `4cab232`).** The §S5 external-repo envelope: four fear-map gates, namespace sandbox, intake hardening, caps, cooldowns, identity split. All ten sub-phases B4.0–B4.8 (incl. B4.2.5) landed CI-green; the full OSS loop is verified end-to-end (intake → four §S5 gates → fork-branch worktree → per-class verifier in-lock against the uncommitted tree → bot-identity commit after the verifier passes → reviewer cert → integrate); SC-3 verified against real WSL containment (`claudedocs/sc3-acceptance.md`; VPS path operator-driven). 24/24 boot-check bodies real; audit 15/0/3.
- **B5 — learning spine + eval discipline. ✅ COMPLETE (closed at `a0537c9`).** Terminal-outcome-on-every-task → retro → CANDIDATE → operator review with the §S7 structural invariants; cross-project memory with verified-before-trusted promotion (Invariant 17). All eight sub-phases B5.0–B5.7 landed CI-green; the full learning-spine loop is verified end-to-end (compositional retro engine → blocking operator review → antibody library + federated trusted memory). **Audit 18/0/0 — full graduation** (Inv 11/12/17 graduated); all four B5 OQs resolved via parallax. **B5 closes the planned rollout B0–B5.** The "every build is a learning input" cut line.

---

## Open Questions (resolve before or during the relevant cut line)

1. **Which seams are hard from day one vs observed-but-not-blocking.** ~~Some gates can start in observe-mode (logging fires without denying) while calibration accrues, then flip to enforce. Single-writer lock, the spec gate, and the OSS fear-map gates are proposed as born-enforcing; which others start observed?~~ **RESOLVED (rev 0.3.66): every gate is born-enforcing; observe-mode was never used and is not a supported state.** Settled by accumulated practice, recorded now: the B2 per-gate decision rule (“decided per gate as it lands”) was applied across all 13 landed gates and every one chose enforcing — grep-verified, no observe/log-only machinery exists anywhere in `gates/` (fail-closed is the harness norm; a soft-firing gate would be the silent-behavior defect class). A future gate wanting an observe phase must amend this resolution first.
2. **Developer form factor.** ~~Headless Claude Code session vs Agent SDK worker for the single writer.~~ **RESOLVED (rev 0.3.7, B2.3): Agent SDK worker.** The advisory roles took the SDK-worker form at rev 0.3.5; the developer (single-writer) half is now resolved the same way by a parallax `decide` (score 84 vs 42, confidence 0.71). The developer is a runtime-driven subprocess: `setting_sources=[]`, tool inventory scoped via MCP servers (parallax + mcp-reasoning + the in-runtime `devharness-aci` ACI server), cwd set to its isolated worktree, per-call cost tracked by the runtime. The SDK-worker form was chosen because the single writer needs the harness to own the tool boundary, the working directory, and per-call cost — all of which the SDK form factor exposes directly, where a headless Claude Code session would mediate them behind its own loop.
3. **Per-class director reasoning budget and tier values.** ~~Invariant 16 fixes that both the reasoning budget and the tier minimum exist and are enforced at dispatch; the specific budget and tier values per task class are set against the B1/B2 baseline. The §S2 table values (≥T0 / ≥T1 / ≥T2) are B1/B2-provisional placeholders.~~ **RESOLVED (rev 0.3.66) on three axes, each to the depth the evidence supports.** **(a) Tier minimums — ratified as-is:** the code floors sit at or above every §S2 floor (`bugfix`/`dependency_bump` enforce T2, stricter than the table’s ≥T1 — compliant, since the table states minimums), and every live dispatch runs the Claude 5 default via `models.py`. **(b) Blast-radius caps — the first evidence-based ratification (#M4):** `feature` crossed the 20-sample threshold (60 realized tasks across 7 projects; observed_max 14 distinct files, p95 11, median 4) and its cap is tightened 30→21 by `ratify.py`’s own `ceil(max × 1.5)` formula, applied as a deliberate operator-authorized act (operator instruction 2026-07-02). `new_project_scaffold` (n=9), `bugfix` (n=1), `refactor` (n=2), `dependency_bump` (n=1) stay at their conservative values — `emit_cap_recommendations` already fires organically in the maintenance window as their telemetry accrues. **(c) Reasoning budgets — ratified as conservative defaults (the B2.8 precedent), with the telemetry gap named:** director token spend is enforced in-memory (Inv 16) but never persisted, so no realized token evidence exists to tighten on; the USD `cost_spent` telemetry (rev 0.3.60, n=2 director samples) accrues the future basis. Re-ratification of (b)/(c) is organic, not a standing open question.
4. **Cross-project memory downgrade policy.** ~~Invariant 17 fixes that `trusted` requires a verification event; the remaining question is staleness — does a `trusted` entry auto-downgrade after N days or M intervening changes, and what re-verifies it?~~ **RESOLVED (rev 0.3.65): deliberately deferred until a production consumer exists, with a structural reopen trigger.** A code-level check found trusted memory has ZERO production consumers — only `boot.py`'s Inv-17 parity check calls `list_verified_memory` (the antibody library bridges *into* memory; no decision path reads *out* of it) — so staleness has no point-of-use impact today and downgrade machinery would be unexercised bloat. Parallax `decide` (78 vs 62 for building the mechanism now, confidence 0.58). Recorded direction for when the trigger fires — the **prune-pattern mirror** (the rev-0.3.35 precedent): an advisory TTL report in the maintenance window, an operator-authorized downgrade (`authorized_by` + `reason` → a `memory_entry_downgraded` event flipping `verified_locally` to 0), re-verification via the existing Inv-17 `memory_entry_verified` path; never automatic, never silent (point-of-use decay and an auto-sweep scored 24/45 — silent state change is this project's standing defect class). The “M intervening changes” axis stays unmeasurable (no memory-entry↔code-churn linkage); TTL is the implementable axis. **The reopen trigger is structural, not aspirational:** `test_memory_store.py::test_oq4_reopen_trigger_no_production_consumer_of_trusted_memory` fails the moment any runtime file beyond the definition + the boot check references `list_verified_memory`, naming this OQ and the recorded direction.
5. **Reviewer composition.** ~~Single parallax-backed reviewer vs a small panel (security/test/quality advisors) feeding one verdict.~~ **RESOLVED (rev 0.3.8, B2.5): single parallax-backed reviewer.** Chosen over the bruno-swarm specialist panel by a parallax `decide` (score 78 vs 66, confidence **0.56** — moderate; a closer call than OQ2's 42-point gap). Rationale: aligns with R4's literal description, minimizes token cost + operator workload, and yields one clean verdict that integrates with the B2.2 pass/fail verifier framework. The panel maximizes calibration diversity (specialist disagreement) but multiplies cost and can require operator adjudication. **Revisitable:** if single-reviewer calibration proves insufficient once calibration data accrues (B2.8+), the specialist panel remains the future tightening candidate.

---

## Revision history

- **2026-07-18 rev 0.4.29.** **Install-easing II: `devharness init` + the first-build walkthrough (operational/onboarding; no invariant change).** The advisory-lite loop worked (charfreq) but wiring it still took the hand-authored steps from that drive. **(1) `devharness init`** (new CLI subcommand, `cli/init.py`): writes the advisory-lite `mcp.local.json` via `json.dump` with the running interpreter's absolute path (never string templating — Windows backslashes), refuses an existing file with the repo's `refused:`/exit-1 shape (`--force` overwrites; a missing `--path` parent fails closed naming it — the open_store precedent), **self-validates** through `mcp.config.server_cfg` (the single source; the env override is set with save/restore in try/finally so in-process test dispatch cannot poison later config tests), warns by ACTUAL gitignore status (`git check-ignore` — the bare pattern matches at any repo depth, so a location-based warning would be false in subdirectories), notices a pre-set `DEVHARNESS_MCP_CONFIG` pointing elsewhere (never silently redirect an operator with real servers wired), and prints the next steps in both shell forms. No persistent env writing (setx rejected: machine-wide state from a bootstrap + the truncation footgun). **(2) `docs/first-build.md`**: the charfreq drive as the worked narrative — install (README-verbatim), `python -m devharness init` (the canonical `python -m` form: a wrong PATH `devharness` would bake the wrong interpreter into the config), the keystroke path N→R/A→v/s→D→W→M with what to expect at each (interview envelope: typically 2–3 rounds, hard cap 5, sometimes one confirmation turn; refutation + auto-retry as normal operation; cost as a generic range — advisory roughly doubles a task's LLM cost, no real-run dollar figures per the rev-0.4.17 posture, `docs/` ships to the mirror unscrubbed), and the troubleshooting ladder (stray `ANTHROPIC_API_KEY`, MCP timeouts, env-var-not-in-this-shell, relative `DEVHARNESS_DB`). Cross-linked from the README quick-start + Deeper docs + local-mcp-setup's bundled-substitute section. Plan adversarially reviewed pre-implementation (3 MAJOR + 7 minor findings folded); **a post-implementation review pass then caught regressions in the ADJACENT rev-0.4.28 code and the new renderer, all fixed here:** the resolved-block ANSWER cap (300) truncated the very multi-point answers that settle later points — re-introducing the re-ask defect for verbose answers (the charfreq round-2 answer exceeded 300; now 1000, with the point COUNT capped at 6 so a server-controlled payload cannot regrow the rev-0.3.78 context balloon); and the progress renderer's brace heuristic both false-positived a legitimate brace-led question and false-negatived a code-fenced payload, while plain-prose questions (a confirmation turn) were silently sliced at the summary length — detection now keys on the elicit payload MARKERS (`divergence_points`/`assumed_objective` key strings): prose renders full, extraction failure shows the unparseable marker, and the ImportError degrade shows a marker rather than a raw machine-JSON slice.
- **2026-07-18 rev 0.4.28.** **The charfreq drive's two findings fixed (§S1 research threading + the console progress line).** **(1) Interview context threads every asked point.** The re-ask root cause was sharper than the drive note: `qa_history` threaded each round through `readable_question_text` — the FIRST divergence point only — so a multi-point round's later points were never named in the next round's context, and the judge could not honor "never re-ask" for a point it was never told about. `resolved_round_block` now enumerates EVERY point (up to 300 chars each — a 150-char cut would leave long questions' substance unmatchable) with the operator's answer once per round, and the payload parse routes through the single parser (`_elicit_payload`) instead of a fifth hand-rolled copy. The adversarial review reshaped the semantics: the block says **ASKED, not RESOLVED** — one answer may not address every point of a round, and declaring unaddressed points settled would make them permanently un-askable (the judge decides coverage from the answer text; a genuine gap may still get a sharper follow-up); and the advisory elicit prompt keeps BOTH the generic never-re-ask rule (fallback `Q:/A:` rounds are still covered) and the ASKED-block-aware instruction. Benefits real parallax identically. **(2) The progress line renders questions readably, and ONLY questions specially.** `frame_line` showed `question_text` — the raw 1.4KB elicit JSON — at full value (the rev-0.4.12 readable fix covered the question card + A-prompt, never the log line). Now question_text renders via `readable_question_text` (lazy import; a mid-object-truncated payload that would fall through to a raw JSON slice shows "(elicit payload — unparseable)" instead — never machine JSON in the pane), while every OTHER value deliberately keeps the full render — the review caught that a generic 300-char cap silently truncated verifier failure `detail`, the operator's only diagnostics surface in the pane. Both fixes review-shaped (8 findings: the RESOLVED-overclaim, the dropped generic rule, the diagnostics truncation, the raw-slice fallthrough, the 150-char cut, the spec-first deviation this entry closes, the fifth parse copy, the over-broad guard).
- **2026-07-18 rev 0.4.27.** **The advisory-lite full-loop drive — charfreq (project 12): the outside-user loop PROVEN end-to-end, two findings recorded.** The first operator-driven console build with BOTH bundled advisory servers wired via `DEVHARNESS_MCP_CONFIG` (no private MCP servers in the chain): research interview (2 elicit rounds, readable through the card/A-prompt renderers, clean termination), spec synthesized + signed, decompose through the advisory-reasoning-booted relay produced a real **6-task plan**, all six tasks **completed** with done earned twice through advisory verdicts — including **two genuine spec_claim refutations** (verify FAILED → rewind → bounded auto-retry → passed: the single-pass judge live-refused wrong claims, not a yes-machine), auto-retro per task (6 clean nulls), zero invariant_violated, project assembled; the artifact (a stdlib `textstat` char/word-frequency CLI, 76 tests green) behaves exactly per the operator's interview answers. Cost $32.80 — roughly double a comparable parallax build (the documented serial-additive nested-judge expectation, now measured). **Findings, each for its own fix cycle:** (1) elicit round 2 partially RE-ASKED the settled encoding point — the prompt's "never re-ask" instruction plus raw Q&A threading is insufficient for a single-pass judge; hardening candidate: thread RESOLVED points as an explicit list in the elicit context (the 0.4.14 quoting backstop correctly did not fire — this was a paraphrase re-ask, a different shape). (2) The progress pane rendered the 1.4KB raw elicit JSON as a wrapped wall — `console/progress.py frame_line` shows `question_text` at full raw value; the rev-0.4.12 readable fix covered the question card + A-prompt but not the progress line (affects real parallax drives identically — the drive made it visible).
- **2026-07-18 rev 0.4.26.** **Advisory-lite — the bundled substitute MCP server (`python -m devharness.advisory --tools parallax|reasoning`).** The rev-0.4.25 research established outside users could run everything except the write loop (the two private MCP servers). Advisory-lite closes that: a FastMCP stdio server inside the runtime package (zero new dependencies — `mcp` is a hard dep of the Agent SDK) satisfying exactly the substitute-server contract `docs/local-mcp-setup.md` documents, wired purely via `DEVHARNESS_MCP_CONFIG` — the tool namespace comes from the config key (verified in SDK source), so no harness wiring changes. **Parallax side:** `verify`/`check`/`grounded_verify` run a single-pass nonce-guarded LLM judgment — untrusted context/diff/sources in a delimited data block, the judge must end with a per-call `VERDICT-<nonce>:` sentinel (unforgeable from the context), and the handler re-renders a **server-constructed one-line JSON verdict** whose raw judge text never reaches the harness (JSON-canonical is load-bearing three ways: the dict path of `parallax_passed`, the narrated verdict-line path, and `parallax_structured_verdict` — a prose verdict would make every non-goals semantic check guaranteed-discarded spend); refuted/unverified renders carry an explicit refutation anchor and the sanitizer scrubs bare pass-words (the any-pass-word fallback); a missing sentinel fails closed as `unverified`. `grounded_verify` refuses empty sources (matching real parallax — accepting would weaken the reviewer gate) and reads named `path[:start-end]` slices byte-capped. `elicit` generates the `divergence_points` payload with one internal validation retry, then a fixed-text error containing no brace (a narrated tool error must not satisfy the shape gate); handler params are `str | None` (research passes `context=None` on round 1 — a pydantic rejection would burn the structural retry and degrade every interview). `diverge` is sanitized plain text. **Reasoning side:** the three fork tools are static handlers, zero LLM (their outputs are discarded; the director's budget reads the relay session's usage). **Model:** `DEVHARNESS_ADVISORY_MODEL`, else the T1 advisory model computed with the `DEVHARNESS_MODEL` pin excluded — an inherited writer pin would silently collapse the verifier-family independence that is advisory-lite's one recoverable form of independence. **Env posture:** the server does NOT pop `ANTHROPIC_API_KEY` — the drivers already pop it, and during a rev-0.4.0 overage retry the key deliberately flows through so the nested call bills the key exactly when the subscription is exhausted. Verdict tools register `structured_output=False` (FastMCP's structured wrapping would put `{"result": "<text>"}` on the wire — `result` is a `_VERDICT_KEYS` member and the full-sentence value is not a pass-word, so a genuine supported verdict could fail closed on a relay echo). **One harness change:** the asterisked/markdown verdict forms join `_INJECTION_MARKERS` — the relay-echo path (untrusted diffs ride in the relay prompt) could re-open first-verdict-line-wins ABOVE the server, and the pre-gate missed the `**supported**` form; this hardens real parallax too. **Honest label (docs):** restores feature/OSS completion (verify is loop-blocking — the spec_claim/spec_criteria axes fail closed in verifier AND reviewer; the prior "only raises the quality floor" doc sentence corrected), raises research/non-goals/retro quality; single-pass judgment, not parallax's multi-pass ensemble; nested-session spend is same-login additive and invisible to SC-6 — a DOCUMENTED SCOPE EXCEPTION, not a violation: SC-6's 'every real spender emits' binds the harness's own clients, and the substitute server is an outside-user process beyond the harness event surface (the inner cost never reaches the relay's ResultMessage); relay paraphrase + judge persuasion stated as residuals. Live validation: a gated test (`DEVHARNESS_RUN_ADVISORY_LIVE=1`, the SC-3 skip pattern) drives the hermetic feature build end-to-end through the real advisory server — verifier + fresh reviewer both. Two adversarial review passes shaped the design (the second falsified four majors in the first: the round-1 `context=None` rejection, the structured-wrapping fail-closed, the relay-echo re-opening, the non-goals dict requirement).
- **2026-07-18 rev 0.4.25.** **Install-easing pass — the single MCP-config source with `DEVHARNESS_MCP_CONFIG`, the jqlite dist-name trap defused, the docs told the truth (operational/config change; no invariant change).** An installation research pass (two exploration agents against the public-mirror surface) found the test/build path works with zero private pieces, but a fresh user hits three first-hour walls. **(1) MCP-config source.** Nine call sites each hand-rolled the same `~/.claude.json` `mcpServers` read (the five `run_*` drivers + `run_promote`, both console readers, and the rev-0.4.0 overage key miner) with no override — users with their own MCP servers could not wire them per-repo, and the requirement surfaced as a runtime crash. Now one module (`mcp/config.py`): `server_cfg(name)` honors **`DEVHARNESS_MCP_CONFIG`** (any JSON file with a top-level `mcpServers` block; an explicitly-set override FAILS CLOSED on a missing/invalid file or absent server — the rev-0.3.63 never-silently-ignore philosophy) and falls back to `~/.claude.json` exactly as before; a parity-guard test bans re-hardcoding the read. The plan's adversarial review shaped the consolidation: `sdk_query.overage_key` and `console/developer._server_cfg` survive as thin delegates (the former is `test_sdk_query`'s autouse monkeypatch seam, the latter is imported cross-module by `console/oss.py`); the overage path preserves its exact rev-0.4.0 semantics (ordered top-level two-name lookup, never a scan) and **degrades to None with one stderr line — never raises — on a bad override** (it runs mid-retry inside every SDK loop; a raise would replace the credit-exhaustion error with a new crash mode); `run_promote`'s deliberately-soft contract stays soft on home-file absence but fails loud under a set override; resolution stays lazy (dispatch-time, not import-time — three tests import the drivers as modules on machines without the home file). **(2) jqlite trap.** `pip install .` at the repo root installed the bundled jqlite demo, not the harness — the dist renames to `devharness-jqlite` (the `jqlite` command/module unchanged; CI never installs the root dist) so an accidental install self-describes, plus a header comment and the README note. **(3) Docs truth.** The console guide's `pip install "devharness-runtime[tui]"` named a package that isn't on PyPI — and the console itself printed the same unpublishable command as its degraded-mode hint (`console/__main__.py`); both now say `pip install -e "runtime[tui]"`. The README quick-start installs `[test,tui]` (the console silently degraded to read-only under `[test]` alone), gains a **"What runs without the private pieces"** boundary table (nothing / Claude login / both servers) so the wall is met in the README instead of as a crash, notes `dev_stack.sh` is Windows-shaped, and unpins the stale spec-rev citation; new **`docs/local-mcp-setup.md`** documents the config sources, a repo-local `DEVHARNESS_MCP_CONFIG` example (placeholders only — the mirror ships `docs/` verbatim), and the review-verified minimal substitute-server surface (parallax `verify`/`check`/`grounded_verify` accepting the `Verdict:` prose line or JSON verdict keys, `elicit`'s `divergence_points` payload shape, `diverge`; mcp-reasoning's three discarded-output forks + the parsed decomposition completion) with the deliberate degradation ladder stated. Advisory-lite (a bundled serverless substitute) researched and deferred as its own decision. **A post-implementation adversarial review (18-agent workflow) found seven confirmed defects in the new surface, all fixed:** shape-blind JSON handling raised `AttributeError` past every `MCPConfigError` catch — including out of `overage_api_key`'s never-raise contract mid-quota-retry — now shape-validated with an error TAXONOMY (`MCPConfigFileMissing`/`MCPConfigFileInvalid`/`MCPServerNotConfigured`, each carrying `is_override`); a set override silently redirected the overage-key lookup away from the home file, disabling the rev-0.4.0 auth-fallback for any keyless substitute-server file — the key lookup now consults the override FIRST and **falls back to `~/.claude.json`** (the key's historical source); a malformed DEFAULT home file silently disabled the fallback — the stderr diagnostic now fires for any unreadable source, not just overrides (absence stays the quiet None); `run_promote`'s soft contract is now precise — soft on *unconfigured* (absent server/home file, even under a valid override without parallax), loud-with-a-clean-exit on *broken* (malformed file, or an override pointing nowhere) — the prior blanket catch masked a corrupted home file to a silent no-parallax promotion; the missing-home-file error (the fresh-clone first failure) now teaches `DEVHARNESS_MCP_CONFIG`; the doc's `mcp.local.json` "gitignored" claim is made TRUE (`.gitignore` entry — the example carries a real API key toward a mirror-bound repo); the parity guard matches any home-dir spelling, not one verbatim string; and six stale "from ~/.claude.json" docstrings across the touched surfaces now name the config source.
- **2026-07-18 rev 0.4.24.** **§S7 duplicate-candidate guard + SRI-hash scanner exclusion — the two defects the rev-0.4.23 backlog drain surfaced.** **(1) Terminal-path duplicate-candidate guard** (`retro/candidate_guard.py`, wired in `RetroEngine._emit_candidate`). The r1 drain (14 terminals, one shared correlation) produced 20 near-duplicate pending antibodies for 2 real defect classes — each terminal re-derives the same defect from the shared history, and the LLM re-words `signature_name`/`pattern_text` every time; separately `devharness.db` accumulated 18 identical `quarantine_blocked` rows, 16 operator-rejected (pending-only dedup re-asks forever on stable texts). The signal path got its guard at rev 0.3.92; the terminal path had none. The guard is per-kind: an **antibody** is suppressed when a queue row of ANY review_state matches exactly on `(COALESCE(signature_name,''), pattern_text)` — the projection NULLs an empty signature_name, the review's catch — **or** shares **≥2** 5-word shingles with a prior `pattern_text` (threshold measured on the real r1 corpus: ≥1 wrongly suppresses one genuinely-different finding via quoted-operator-answer boilerplate ("yes that is the goal"); ≥2 → 0 wrong suppressions, 20→7 — ~65% noise reduction, not total collapse, stated plainly); a **gate-change** is suppressed only while a PENDING row matches `(target_gate, change_kind, signature_name)` — signature_name is load-bearing (four signatures share `("verifier_attached_gate","tighten")`; without it a pending baseline-axis candidate would swallow a later post-pass/Brier-drift finding), and post-review re-emission stays intentional (the 0.3.92 design). The exact clause is load-bearing for the short static texts (quarantine = 4 tokens = zero 5-shingles); all three sources (`llm`/`quarantine`/`t0`) are covered for antibodies — T0 per-terminal evidence survives in `retro_run.t0_matched_signatures`. The 0.4.14 shingle math is extracted from the interview backstop's closure into `textsim.py` (behavior-preserving; the re-ask backstop refactors onto it); `conn` threads additively through `analyze` (default None = no dedup — the signal path and direct-call tests are untouched); additive `candidates_suppressed_count` on `RetroResult`/`RetroRun` (no schema bump/migration/catalog regen, Inv 8 unaffected — suppression is pre-emit, replay only re-applies logged events). Residuals: the guard saves queue noise, not LLM spend (post-LLM by construction); a new defect sharing ≥2 shingles with a rejected candidate is suppressed (measured 0 on r1; escape hatches: the suppressed count, the queryable queue, approve-by-row-id works on any state). **(2) SRI-hash exclusion in the injection scanner** (`oss/injection_scan.py`). The a private build drain quarantined a clean terminal because an npm `package-lock.json` integrity hash (`sha512-<88-char base64>`) tripped `encoded_payload` — the `-` in the prefix sits outside `_BASE64_RE`'s char class, so the matched run is the bare base64 body the a81cfd2 pure-hex exclusion can't cover; the terminal is permanently consumed (the dedup key offers no re-analysis), so the fix is forward-only. A run is now excluded iff the 7 chars preceding it are `sha256-`/`sha384-`/`sha512-` AND its length is exactly the per-algorithm SRI length (44/64/88 incl. padding — all three prefixes are 7 chars, so a fixed slice beats a lookbehind, which couldn't pair length to algorithm); bare or wrong-length runs still flag, so no arbitrary-length payload rides the exclusion (residual: an exactly-SRI-sized payload behind a `shaN-` prefix passes — same class as the pure-hex residual; glued prefixes are excluded too). This also cures a **real OSS-intake false-positive class**: a legitimate repo README carrying a CDN `integrity="sha384-…"` snippet was previously rejected at intake as `injection_detected` — an accept/reject behavior change on the fail-closed gate, named deliberately. **A post-implementation adversarial review (16-agent workflow) reshaped the guard's rules and hardened the exclusion — five confirmed findings, all fixed:** the dedup is now per-SOURCE — **quarantine** antibodies are PENDING-only exact and never shingle-matched (a multi-pattern list DOES form shingles, so a superset pattern combination — a genuinely different hostile record — would have been suppressed; and any-state would have made a post-review injection campaign invisible: one rejected false positive would silence every later hostile terminal forever), **t0** antibodies stay any-state exact (per-terminal evidence survives in `t0_matched_signatures`), **llm** antibodies keep any-state exact-or-shingles with the shingle pool scoped to llm-sourced rows; an **empty-signature LLM gate proposal is never deduped** (two different proposals on one gate+kind would collide on the empty key and the loser's terminal is consumed — permanently lost); the SRI prefix compare is **case-insensitive** (SRI algorithm tokens are, per the spec — an uppercase `SHA384-` snippet would have re-opened the false positive). The review also named the SRI chaining recipe (`sha512-<exactly 88 chars>` chunks) as an intake-bypass channel; weighed and accepted with the containment stated honestly: the pre-existing pure-hex exclusion is UNBOUNDED (arbitrary-length hex payloads already pass), so the length-anchored carve-out adds no materially new smuggling channel to a tripwire detector nothing downstream decodes — while the alternative was live false-rejects of legitimate repos at the fail-closed gate.
- **2026-07-18 rev 0.4.23.** **§S7 learning-spine remediation: T0 verifier-failure signatures match structure, not prose + retro runs where builds happen.** A spine review against all 16 real stores found two defects. **(1) The three `verifier_failure_*` T0 signatures were prose-substring predicates** — "baseline"/"post"/"behavior" anywhere in `verifier_outcome.detail`. The failing verifier's test-output tail is appended to `detail`, so a pytest-asyncio deprecation warning ("…avoid unexpected behavior…") fired `verifier_failure_behavior_change` on a `dependency_resolves` failure (a private build) and a `feature_spec_claim` failure (a private build) — 4 operator-rejected candidates, 0 accepted, two independent cycles (the "canned-signature noise" the a private build retro flagged). Worse, the signature was **dead against its intended target**: the refactor verifier's real axes are `test_added`/`test_removed`/`pass_to_fail`/`fail_to_pass` (and its empty-capture message spells "behaviour"), so the token never appears in a genuine refactor failure. Fix: `_verifier_failed` now requires the structured `verifier` field (`bugfix_regression` for baseline/post, `refactor_behavior_preserving` for behavior_change), `passed is False`, **the terminal's own `task_id`** (a plan's tasks share one correlation, so an earlier task's failure would otherwise re-fire as a duplicate, wrongly-attributed candidate on every later terminal — the adversarial review's catch), and the stable `"<axis> axis failed"` reason **prefix** (the output tail comes after it and can never match). Deliberately unsignatured: the `suite_passes`/`test_suite` axes and non-axis reasons ("regression_command missing", "class fields missing", the refactor empty-capture) — a plain red suite is the ordinary verifier signal, not a gate-tightening pattern. Signature names/templates unchanged (event compat). **(2) Retro coverage was coupled to the manual single-store maintenance script** — `retro_run` had exactly one live caller (`run_maintenance`), so console/panel-driven builds never fed the spine: 9 stores held terminals with zero retro runs (~70 unanalyzed). Fix: the drain loops are extracted to `retro/drive.py` (`drain_terminal_retro`/`drain_signal_retro`, both preserving the rev-0.3.57 `LLMUnavailable` halt — down SDK ⇒ queue intact; **`held` reported distinctly from queue-empty**, so a store whose fermata is permanently held by an orphan `running` lifecycle row — a private build's live case — is visible, not silent), and retro now runs **(a) automatically post-build** in `ConsoleDeveloper.dispatch` right after the invariant sweep (full engine incl. T1 LLM residue; one advisory guard around the whole block including client construction — a missing `~/.claude.json` parallax entry must not break a build; residue spend emitted as `retro_residue` under the stable `maintenance` correlation, not the build's — the drain also consumes other correlations' backlog), **(b) on demand from the TUI** (`L`) and **(c) the panel** (`POST /retro/run`, Host-gated like every route), plus `run_maintenance --retro-only` (retro + sweep + signal drain only) for backlog drains. The signal path was audited sound — `invariant_violated` emits live in every build, `fault_handling_regression` correctly crosses from the hermetic oracle store — zero events = zero breaches; no change. **A post-implementation adversarial review (17-agent workflow) caught five more defects, all fixed:** the verifier signatures still re-fired on a re-driven task's COMPLETED terminal (retro dedup is `(task_id, terminal_kind)`, so the first attempt's failure sits in the success's preceding_events with a matching task_id — now gated: a completed terminal never fires them, which also matches the operator's a private build rejection of a corrected-failure candidate); realized T1 residue spend was LOST from the SC-6 ledger when a drain raised mid-pass (the cost emission now sits in a `finally` — the analyzed terminals' retro_runs exist, so the spend would be unrecoverable); the auto-drain was UNBOUNDED (a first dispatch on a backlog store blocked through the whole backlog inline — now capped at 5 terminals per build, deep backlogs belong to the explicit surfaces, and `DEVHARNESS_RETRO_NO_LLM` drops the auto path to free T0-only as the spend kill-switch); the panel silently dropped a done job's result (only errors surfaced — the HELD/HALTED summary now renders on a job line); and the `held` flag was a TOCTOU (now sampled before the loop). Accepted residual (documented in `retro/drive.py`): two processes CAN drain one store concurrently (panel dispatch vs a run_maintenance window) and double-analyze a terminal — bounded double spend + a duplicate candidate that lands in the BLOCKING review queue; a cross-process drain mutex is deliberately not built for an advisory spine.
- **2026-07-17 rev 0.4.22.** **The CLAUDE.md mirror trim is an explicit section allowlist, not window surgery.** `transform_claude()` deleted everything between two anchor headers and kept the entire tail — so any section added after `## Architecture at a glance` (a future one, or one carrying sensitive content) shipped to the public mirror by default. Replaced with an explicit keep/drop: the public CLAUDE.md is the preamble + the summary + exactly the allowlisted H2 sections in source order; an UNLISTED section is DROPPED (the fail-safe direction — a new section never silently leaks), and `_require` asserts each kept section is present so a rename/removal HALTS the mirror build instead of dropping content. Verified: all 11 kept sections survive, a renamed section halts the build, and an injected `## Operator secret notes` section is dropped (not shipped).
- **2026-07-17 rev 0.4.21.** **Verbatim operator research content removed from CI-wired tests +
  private-build fingerprints scrubbed from code (the mirror only transforms docs, so code ships as
  source).** `test_reask_backstop.py` reproduced the operator's ACTUAL research-session answers (a
  live-store corpus — the assumed_objective, full divergence questions, and answers of a real
  feature-design interview) as regression evidence; it is now a SYNTHETIC two-interview
  reconstruction (a temperature-converter + a CSV-column-selector) preserving the exact property
  the detector was measured against — a later round quoting a verbatim run from a prior answer
  (margins pinned ≥2), plus the non-overlapping cross-interview control. The real corpus is retained
  only in the private repo's git history, not shipped. Separately, the operator's private-build
  project names (separate repos on the operator's machine) that appeared in ~30 `runtime/` + `tests/`
  comments and functional fixtures were replaced with generic provenance ("a prior drive") or clean
  synthetic fixture values (store names, `assumed_objective`, diff paths) — the docs keep them
  (design-history value) and the rev-0.4.20 mirror transform scrubs the docs, but CODE ships
  verbatim, so it is now source-clean. And `prepare_public_mirror.sh` now excludes ITSELF +
  `_public_mirror_transform.py` from the mirror: the transform enumerates the fingerprint tokens
  literally (its scrub list), so it must not ship — the boundary is documented narratively in
  CLAUDE.md instead. Full suite green (1572); the reask backstop's 5 tests pass on the synthetic
  corpus.
- **2026-07-17 rev 0.4.20.** **The mirror transform now redacts private-build fingerprints from the
  KEPT revision history.** The operator kept the spec rev-history for its design-decision value
  (rev 0.4.18) — but `transform_spec()` only removed the briefs bullet, so every operator
  private-build name (the ~9 console/script-driven builds — separate repos on the operator's
  machine, NOT in this repo) and their live-store `.db` events would have ridden the kept body
  into the public mirror (~145 occurrences across the spec + CLAUDE.md + README + CHANGELOG). A
  shared `_scrub_private_builds()` now redacts them to "a private build" across all four kept
  public files, applied AFTER each structural transform. Guards: the in-repo CI-wired subdir
  projects are preserved (they are legitimately public); the bare word "dedup" (deduplication — a
  legitimate technical term used dozens of times) is NEVER scrubbed — only the project-dir and
  store compound forms are; and `transform_spec()` gains a `## Revision history` fail-closed anchor
  so rev-history format drift halts the mirror build instead of silently leaking. Mirror-only — the
  private repo keeps the real names. Verified on working-tree copies: every fingerprint token zero
  in the transformed output, the public projects + "dedup" intact.
- **2026-07-17 rev 0.4.19.** **Public/private-boundary documentation + `SECURITY.md` + gitignore
  hardening.** Completes the go-public process: a new `## Public repository boundary` section in
  `CLAUDE.md` (placed in the trim's KEPT region so it survives into the public mirror) documents
  exactly what is withheld and why — excluded files, trimmed narrative, compressed CHANGELOG,
  genericized identifiers (revs 0.4.15–0.4.18), and the operator-supplied MCP-server clone URLs.
  New `SECURITY.md` documents the fail-closed host-shell guard (`aci/host_exec.py` —
  `DEVHARNESS_ALLOW_HOST_SHELL`/sandbox), the sandbox tiers, the panel's CSRF-only request gate
  (not access control), the real-money/real-PR/API-rebill warnings, the no-real-secrets posture,
  and a private-advisory reporting path; README links it. `.gitignore` gains `var/` and
  `.claude/settings.local.json` (the DBs were already covered by `*.db`; nothing sensitive was
  tracked — latent gap closed). LICENSE copyright kept as the generic "devharness contributors"
  (operator decision — consistent with scrubbing operator identity). No runtime behavior changed.
- **2026-07-17 rev 0.4.18.** **Release-content decisions + the deterministic mirror-prep tooling.**
  The operator settled what the public fresh-history mirror contains (the private repo stays the
  full archive): **exclude** the operator-context files (`HANDOFF.md`, all of `claudedocs/`, the
  two architecture briefs, the Solo-Developer essay); **trim** `CLAUDE.md` to architecture +
  conventions + operational invariants (drop the session-by-session narrative, ~440→~138 lines);
  **compress** `CHANGELOG.md` to one header per arc/cut-line (SHAs + dollar figures dropped);
  **keep** the spec revision history in full (legitimate design-decision history). Encoded as
  `scripts/prepare_public_mirror.sh` + `scripts/_public_mirror_transform.py` — a deterministic,
  reviewable transform run on the orphan/release branch at flip time (refuses to run on `main`;
  asserts every doc anchor so drift fails loudly; also fixes the navigation references the
  exclusions would dangle — README doc-lists, the spec source-material pointer). Tested against a
  throwaway orphan clone. **Accepted residual:** historical prose inside the KEPT revision
  histories still cites `claudedocs/…` + dead SHAs — read as "see the private archive" per the
  README note; scrubbing every historical sentence is out of scope. No runtime behavior changed.
- **2026-07-17 rev 0.4.17.** **Operational-fingerprint sanitization — cloud vendor, local paths,
  real-run costs.** The tier-2 sweep: individually non-identifying, but a federated search ties
  them to the same operator. **(1) Cloud vendor** — the ~20 cloud-provider-name mentions in
  user-facing narrative + code (`devharness-spec.md`, `CLAUDE.md`, `CHANGELOG.md`, `HANDOFF.md`,
  `specs/implementation-plan-v0.1.md`, `sandbox/vps.py`) genericized to "the VPS"/"a managed VPS
  (Ubuntu 24.04)"; the specifics stay only in `claudedocs/` (operator artifacts:
  `operator-infra-plan.md`, `sc3-acceptance.md`, `tech-debt-register.md`). **(2) Local Windows
  paths** — the drive-letter project-path strings in `CLAUDE.md` (project locations,
  the machine-migration sentence, the mcp-parallax local path) dropped to bare project names /
  generic descriptions; the launcher code + WSL tests keep their paths (fixtures, not narrative).
  (The sweep tokens — the vendor name, the drive-letter paths — are deliberately not reproduced
  in this entry, so it never matches its own greps.)
  **(3) Real-run costs** — the specific dollar figures in `CLAUDE.md`/`devharness-spec.md` narrative
  removed (kept meaning: "assembled", "completed first-try", "on real spend"); `test_console_tui.py`
  fixtures keep theirs. No code behavior changed; sandbox launcher tests green.
- **2026-07-17 rev 0.4.16.** **Sanitization completion — the GitHub-username residuals the
  0.4.15 "username stays" carve-out wrongly kept.** Rev 0.4.15 ran a private-origin-URL grep
  (zero) but deliberately kept the bare operator GitHub username under a carve-out; the operator
  overrode that — the bare-username grep had never run, and one hit was in `bootstrap.sh`, which
  EXECUTES on a reader's box. Four tracked occurrences removed: `bootstrap.sh` clones the two MCP
  servers from the operator's account (now two fail-closed env vars `DEVHARNESS_PARALLAX_REPO_URL`
  + `DEVHARNESS_MCP_REASONING_REPO_URL`, mirroring the 0.4.15 `DEVHARNESS_REPO_URL` treatment; the
  deploy README's provision block documents all three); `docs/operator-console-guide.md`'s example
  console output (`by <operator>`); and `claudedocs/operator-infra-plan.md`'s live-PR reference
  (username + exact throwaway-sandbox repo name genericized). The tree-wide operator-username grep
  is now zero; the remaining `github.com/*` hits are all third-party (rust-lang, vitejs, test
  fixtures). The lesson: a URL-scoped grep is narrower than a username-scoped one — the sweep must
  key on the identity token, not one of its containers (and the cleanup entry itself must not
  reproduce the token — the self-naming trap this rev-0.4.19 note closes).
- **2026-07-17 rev 0.4.15.** **The public-readiness pass — identity sanitization + the panel
  request gate.** Preparing the repo for a public fresh-history mirror (a NEW repo; this one stays
  the private archive — GitHub serves unreachable commits by SHA, and the docs cite the old SHAs).
  Three read-only sweeps (secrets/history/exposure) found no credentials ever committed but two
  blockers, both closed: **(1) infrastructure-identity sanitization** — the seven tracked files
  identifying the operator's live VPS (IP, DDNS domain, ssh user, key path, sudo posture, panel
  basic-auth user + path prefix, box model, sibling-service clauses) are placeholder-templated
  (`claudedocs/operator-infra-plan.md`, `sc3-acceptance.md`, the four `deploy/vps/` files,
  `HANDOFF.md`), the PAT-incident sentence deleted, the sibling-project codename scrubbed
  tree-wide (its distinctive label alone re-derives the DDNS domain in one guess), and
  `bootstrap.sh`/CLAUDE.md no longer hardcode the private origin URL (clone URL now
  `DEVHARNESS_REPO_URL`, fail-closed). Completeness is defined by greps, not line lists — the
  IP, the DDNS domain + provider token, the codename, the ssh-user-at form, the home-directory
  path, the scoped key-path, the case-insensitive sudo-posture phrasings, the tree-wide panel
  path token (sole accepted residual: the `faultinjection/hermetic.py` fault-store prefix), the
  identity-form bare-username, the co-hosted-services word in `deploy/`, the private-origin
  URL — all zero (the sweep tokens are deliberately not reproduced here, so this entry never
  matches its own greps). **(2) the panel request gate**
  (`PanelHandler._gate_refusal`): every request — GET included, since a DNS-rebound hostname
  resolving to loopback is SAME-origin and CORS never applies — must present a Host that is
  loopback (`127.0.0.1`/`localhost`/`[::1]`, any port) or `DEVHARNESS_PANEL_PUBLIC_HOST` (new
  env; may carry `:port`; case-insensitive; absent/duplicate Host → 403 fail-closed). POSTs
  additionally require a present Origin to be loopback or `https://<public-host>` (no Origin —
  curl/ssh — passes; `Origin: null` is refused), killing drive-by CSRF including the
  `enctype=text/plain` form-smuggling path. The `Access-Control-Allow-Origin: *` wildcard is
  dropped at both emission sites (`_send_json` + `_diag`). 8 new gate tests (hostile/loopback/
  absent/null Origin, rebound Host on GET+POST, public-host admit incl. mixed-case + `:port`,
  raw-socket absent/duplicate Host, IPv6 loopback, no-wildcard assertions). **Deploy note:** the
  reverse proxy must forward the ORIGINAL Host (Caddy default does; nginx default rewrites), and
  the live box needs `DEVHARNESS_PANEL_PUBLIC_HOST=<its domain>` in the unit (manual edit +
  daemon-reload + idle restart) WITH this code deploy, else every proxied request 403s. Plus the
  polish list: README safety section (real spend, the rev-0.4.0 API-key rebill consent note, OSS
  PRs, the never-unproxied rule, the operator-local MCP-server boundary), stale figures refreshed
  (28 tiles, 0001–0028, spec/plan revs), CONTRIBUTING's migration range + CI-matrix + retired
  count-pinning sentences corrected, `license` fields in `runtime/pyproject.toml` +
  `sidecar/Cargo.toml`, `schema/README.md` filled, and the docs-are-operator-context disclaimer
  (private-history SHAs don't resolve in the public repo). The sidecar's read-only SSE CORS is
  out of scope (separate surface).
- **2026-07-17 rev 0.4.14.** **The re-ask backstop detects answer-quoting confirmation rounds.**
  Three interviews on the deployed panel (a private build, the /dev/null bugfix, the annotations
  feature) each ran exactly three rounds, rounds 2–3 re-asking already-answered questions —
  citing the operator's answers verbatim as their divergence signals — and the rev-0.3.86
  Jaccard backstop never fired. Investigated against the store's six real payloads and four
  answers, replayed through the real code: (1) the signal-anchor premise INVERTED — since
  answer-threading, a re-ask round's signal quotes the operator's latest answer, new text every
  round, so identical first questions scored Jaccard 0.222 against the 0.5 threshold; (2)
  first-point-only tokenization vs 1–3 shuffling points; (3) the `asked >= min_questions` gate
  structurally exempted round 2, so every interview paid for at least one undetectable
  duplicate. New deterministic `_answer_quote_reask`: 5-word shingles over the divergence
  question+signal text (parse-miss → full text; assumed_objective/governing_preferences
  excluded — elicit legitimately updates those from the threaded Q&A) vs each prior operator
  answer; any shared shingle ends the interview. Measured against the live corpus: 4/4 guilty
  rounds fire at margins 2/18/3/13; the cross-interview control stays quiet; n=5 chosen over
  n=6 for margin (two rounds sat at exactly one 6-shingle) and the margin itself is pinned ≥2
  in the regression tests. Gated `asked >= 1` — a round quoting an answer back is never a first
  real question — closing cause 3; the min_questions floor is therefore no longer hard (its
  0.3.86 comment updated; no other consumer). The Jaccard stays as the secondary for
  non-quoting rewords. Placement is strictly below the `_no_divergence` confirmation branch and
  test-locked: a confirmation payload's assumed_objective may legitimately echo the answer, and
  firing there would resurrect the rev-0.3.68 no-interview regression. The corpus (six payloads
  + four answers verbatim from `a private build.db`) ships inline in `test_reask_backstop.py` as the
  regression evidence. Three plan-review rounds (third zero-amendments) + a diff review (margin
  assertion + fallback-parity catches folded). Out of scope, recorded: the generation-side
  cause (elicit re-flags seed-vs-clarification conflicts as open divergences — the parallax
  repo, its own cycle on operator assignment).
- **2026-07-16 rev 0.4.13.** **Foreign sqlite files are invisible to the store surfaces.** Live:
  the deployed dashboard's notice banner named `parallax.db` — the parallax MCP server's OWN
  database, co-located in `var/` by the VPS bootstrap — as the freshest store. Every `var/*.db`
  was treated as a devharness store; a foreign file has no `events` table, so the activity
  ranking fell back to file mtime (always fresh for a constantly-written MCP database) and it
  won. Three surfaces inherited the error — the freshest-store default (a bare launch would
  OPEN it), the notice, and the Switch dropdowns (panel + TUI) — and the hazard behind all
  three: every open path runs `migrate()` on connect, so adopting a foreign file writes
  devharness schema INTO it. New tri-state `is_event_store` in `migrate.py` (True / positively-
  not-a-store / unreadable-right-now — the plan review's substantive catch: a blanket
  False-on-any-error would misclassify a locked REAL store, since every devharness store is WAL
  and `mode=ro` can fail shared-memory setup; the probe mirrors `cli/sweep.py`'s two-step, with
  the fallback opened `mode=rw` so a TOCTOU-vanished file is never CREATED by the probe — the
  diff review's catch). Gated surfaces: `_default_db` ranking skips positive-foreign only
  (unreadable still ranks by mtime, today's behavior); the open gate in `_resolve_db` +
  `ConsoleApp.connect` + `cli/_bus.open_store` (the rev-0.3.71/0.3.80 parity set) refuses an
  existing non-store with `FileNotFoundError`/`SystemExit` matched to each surface's existing
  catch sites — so `Panel.switch`, `new_project` name-collisions (e.g. a project literally named
  `parallax`), the TUI P/N flows, and all eight CLIs refuse cleanly instead of migrating; both
  discovery lists omit positive-foreign entries while a transiently-unreadable real store keeps
  its `(unreadable)` row. Accepted edges recorded: an existing never-migrated empty file is
  refused with delete-or-rename guidance; `serve()` with an env-named foreign file exits (a 5s
  systemd crash-loop with a clear journal line — the live unit pins a real store). Two review
  rounds on the plan + a diff review (one behavioral catch folded). Recorded out-of-scope:
  relocating the MCP databases out of `var/` (operator infra call); the seven `scripts/run_*`
  drivers still lack both this gate and the 0.3.63 hygiene (their own parity cycle).
- **2026-07-15 rev 0.4.12.** **The question card renders the COMPLETE question, readably.** The
  a private build drive's first real divergence round put a raw JSON wall on the operator's card:
  `question_text` has always been the FULL elicit payload, and rev 0.4.10 swapped the card from
  the 400-char readable summary (unanswerable when cut mid-assumption) to the raw stored text
  (complete — but machine JSON; the a private build validation looked right only because a confirmation
  turn is composed prose). Both prior renderings were wrong on the same axis: the operator needs
  the FULL content in READABLE form. Worse, the TUI's answer prompt had the same defect in
  summary form — `readable_question_text(text, 400)` shows only the FIRST divergence question,
  so a four-question round (live, a private build) was answered three-quarters blind. New shared
  `full_question_text` (`roles/research.py`): gated by the emitter's own `_elicit_payload`
  (formatter and interview loop agree by construction; confirmation turns / discovery prose /
  operator passthrough return byte-identical), composing the objective + a numbered list of
  EVERY divergence question with its signal + the stated-preference "Assuming:" bullets —
  defensive throughout (non-list containers, non-dict entries, null questions rendered never as
  the literal `None`; broad passthrough on any failure — it runs on the panel's `/state` hot
  path where a raise kills the whole Drive pane). Panel `pending_question` gains `display`
  (`text` stays raw for API compat, `readable` stays the one-line hint); the card renders the
  `display||text||readable` chain via `textContent` and `.q` gains `white-space: pre-wrap` (the
  plan review's blocker: default CSS collapsed every newline — even the confirmation turn's
  bullets rendered as one blob). The TUI answer prompt renders the full text (modal may clip on
  a short terminal — accepted, no truncation reintroduced). Three plan-review rounds
  (review-until-clean; the third returned zero amendments) + a clean diff review. Recorded
  out-of-scope: the progress-log raw `question_text=` leak; the rev-0.4.11 silent-degradation
  observability (both awaiting operator direction).
- **2026-07-15 rev 0.4.11.** **A tool error can never reach the operator as an interview
  question.** The FIRST research start on the deployed panel (a private build) hit a parallax server
  failure (`-32603: divergence arrays disagree`); the SDK worker session caught it, narrated it as
  prose, and finished SUCCESSFULLY — `CallResult.is_error` describes the session, not the tool
  inside it — so the rev-0.3.76 guard never fired and the narration fell through
  `_no_divergence`'s parse-failure path into `question_asked`, reaching the operator's question
  card verbatim (evidence: `a private build.db` #3 on the VPS). Fixed per the full process this time —
  troubleshot from the store, design parallax-validated (`decide`: sequenced fix 88 vs deep-only
  74 vs narrow-only 68), plan adversarially reviewed BEFORE implementation (its blocker: the
  diverge fallback would have leaked the SAME narration into an assumption one call later — its
  guard checks only `is_error`), operator-approved, then implemented. The change:
  `_elicit_payload` gates every interview round on payload SHAPE — key PRESENCE of
  `divergence_points` (the server contract always serializes it; presence-not-truthiness, so the
  legitimate `{"divergence_points": []}` no-divergence shape still reaches the rev-0.3.68
  confirmation turn), never keyword-scanning worker prose (the refuted heuristic class). A
  shapeless or EMPTY result is an errored round: one retry per interview (parallax failures are
  stochastic — the recorded retry convention; the per-interview grain avoids retry storms), then
  break to synthesis like the is_error path — and on that STRUCTURAL break the diverge fallback
  is SKIPPED for the neutral placeholder (the plan-review blocker; the is_error break keeps
  diverge, screened by its own guard — the deliberate asymmetry). Old fixtures feeding bare-prose
  elicit results (never the real contract shape) updated across three test files; the diff
  review's wrong-reason-green catch (repo-grounding fixtures silently traversing the new errored
  path) folded. Deferred to their own cycles: the client-layer truth-fix
  (`CallResult.is_error` from the FINAL per-tool outcome — in-session-recovery misflag risk) and
  the parallax server's own generator bug (separate repo). Live re-validation on the deployed
  panel is the operator's next drive.
- **2026-07-14 rev 0.4.10.** **The panel question card renders the FULL question.** The a private build
  bugfix interview's confirmation turn was cut mid-assumption at 400 chars — the card rendered
  `pending_question.readable` (the 400-char summary meant for the one-line header hint) instead
  of `.text`, inverting the documented contract (`panel/state.py pending_question`: "the
  Research pane renders text (full) and the Drive hint uses readable"). An unreadable
  confirmation turn is unanswerable — the operator confirms what they can read (the rev-0.3.54
  readable-question class, one surface over). One-line UI fix: the card prefers `.text`.
  Found live mid-drive; the full question was read from the store to unblock the interview.
- **2026-07-14 rev 0.4.9.** **Rust `bugfix`/`refactor` verifier commands — the last deferred
  non-Python class gap.** Built before the a private build drive (the rev-0.3.98/0.4.8 precedent): the
  pytest-only `regression_command`/`pass_fail_command` (C0f) made a cargo bugfix/refactor
  structurally uncompletable. cargo has no per-test-file runner and no machine-readable format on
  stable, so both builders now dispatch on `language_for_test_command` (MOVED from
  `_test_coverage` to `class_commands` — the builtin package imports class_commands, so the import
  direction only works that way; re-exported at the old location) and Rust gets two self-contained
  `python -c` wrappers over the stable `test <name> ... ok|FAILED|ignored` output:
  **regression** runs the derived `tests/<stem>.rs` integration target via
  `cargo test --test <stem> --no-fail-fast` and passes only when ≥1 test ran with 0 failures —
  cargo prints "0 passed … ok" and exits 0 for a no-match target, a vacuous pass the wrapper
  refuses (the C0 false-certification class); a compile error is a failure, which at baseline is
  the demonstrated-bug state the overlay axis expects. **pass/fail** emits one sanitized
  `<id> pass|fail` line per test across all targets, with the doc-test `(line N)` suffix STRIPPED
  (a line-shifting behavior-preserving refactor would otherwise rename every doc-test below the
  change — guaranteed false-reject; review catch, live-verified) and duplicate ids across targets
  deterministically `#2`-suffixed (a fail in one target must not be masked by a same-named pass in
  a later one — review catch). Rust regression derivation accepts only direct-child `tests/*.rs`
  integration targets (subdirs are helper modules, unit `#[test]`s in src have no per-file runner);
  the fail-closed rejection text now NAMES that per-language rule so the retry's worker can comply
  instead of repeating the miss (review catch — the natural Rust instinct is a unit test, exactly
  what derivation excludes). The `baseline_should_fail` overlay collection is language-aware too
  (Python-only detection would have left the Rust baseline "failing" on a missing test target —
  the rev-0.3.73 false-certification class reopened). js/go match NOTHING (fail closed naming the
  gap) rather than guessing with Python rules. All four drivers updated (console + script,
  internal + OSS — the rev-0.3.71 parity class; the OSS pair was the review's fourth catch).
  Behavioral tests run the wrappers against a real throwaway crate (baseline-fail/post-pass, the
  vacuous-zero guard, doc-test id stability, duplicate-id suffixing; skipped where cargo is
  absent). Ecosystem coverage: bugfix/refactor now python+rust; dependency_bump pip+npm; cargo
  bumps and js/go bugfix/refactor remain deferred to their own drives.
- **2026-07-14 rev 0.4.8.** **npm `dependency_bump` support — built before the drive (the a private build
  precedent).** Prepping the first npm bump (a private build; a devDependency, which the signed spec's
  "no npm/third-party RUNTIME dependencies" non-goal does not exclude — and the guard's
  deterministic heuristic verifiably cannot trip on it) found `derive_bump_fields` Python-only:
  `package.json` was not a manifest kind, so every npm attempt would fail closed — structurally
  uncompletable, the a private build lesson. The `dependency_resolves` verifier's four axes are already
  language-agnostic; only derivation grew: `package.json` → kind `npm`; the (name, version) pair
  comes from parsing the WORKTREE manifest as JSON (the four dependency sections) INTERSECTED with
  diff-added keys — so JSON noise on added lines (`"version"`, `"name"`, `"engines"` entries) can
  never match — with the range prefix stripped (`^10.1.3` → `10.1.3`); resolution via
  `npm install --dry-run` (path resolved with `shutil.which` — npm is `npm.cmd` on Windows; absent
  npm leaves `bump_command` empty → fail-closed naming it); `package-lock.json`/
  `npm-shrinkwrap.json` join the lockfile names, now KEYED BY ECOSYSTEM (a stray `poetry.lock` in
  an npm worktree must not become the bump's lockfile — review catch). The adversarial review's
  other folded catches: a name in two sections with DIFFERENT specs yields 2+ pairs → the ambiguity
  rule fails closed (a dict-merge would silently certify the later section's version); compound
  range specs (`>=10 <11`, `||`) are unpinnable → no pair; a mixed-ecosystem diff UNIONS pip+npm
  pairs → ambiguity → fail closed. Also: the seeded new-target `.gitignore` gains `node_modules/` +
  `target/` via a shared `SEEDED_GITIGNORE` in `worktree/hygiene.py` imported by BOTH the TUI and
  panel `prepare_target` (a rev-0.3.71-class parity pair; `node_modules` stays ignored-not-purged
  per the recorded rev-0.3.98 decision — deleting installed deps breaks non-reinstalling test
  runs). Pip derivation byte-identical (guarded by the existing 7 tests; +4 npm tests). Deferred
  still: cargo bumps, non-Python bugfix/refactor commands. One operator-side pre-drive check
  carried to the run-book: confirm `npm install --dry-run` exits 0 and leaves `package-lock.json`
  byte-unchanged on this npm version (the reviewer's environment could not execute npm).
- **2026-07-14 rev 0.4.7.** **New-project takes a test command.** The panel's (and TUI-inherited)
  New-project flow hardcoded the target's test command to `python -m pytest -q`; on the first
  non-Python panel project (a private build, Node) the verifier ran pytest against the Node repo
  ("no tests ran", exit 5) and rejected a HEALTHY scaffold task (the run-book's
  manual re-set step existed precisely because this was predicted — the drive turned the prediction
  into evidence). The New-project form gains a test-command field (`/project/new` passes
  `test_command` through to `set_target`); blank still defaults to pytest, so existing Python flows
  are unchanged. The mid-drive recovery (re-set target with `| node --test`, then the task row's
  Retry) exercised the rev-0.4.3 Retry button on its first real blocked task.
- **2026-07-14 rev 0.4.6.** **The panel's auth default matches the repo's clear-stray-keys
  convention + job errors carry the subprocess stderr.** The first a private build research start from a
  fresh shell died with a bare `Exception: Command failed with exit code 1 … Check stderr output
  for details`. Two defects: **(1)** a machine-level stray `ANTHROPIC_API_KEY` (present on the
  operator's box) reached the `claude` subprocess — the TUI and all seven `run_*` drivers CLEAR a
  stray key unconditionally (subscription auth on the interactive box), but the panel only cleared
  it behind an opt-in `DEVHARNESS_PANEL_SUBSCRIPTION=1`, so every fresh shell inherited the broken
  mode; the panel deviating from the convention was the defect. `_resolve_auth` now clears the
  stray key BY DEFAULT; precedence: a systemd-bridged `$CREDENTIALS_DIRECTORY` credential keeps
  API-key auth (the VPS — its unit is credential-file-only, verified no regression), an explicit
  `DEVHARNESS_PANEL_APIKEY=1` keeps an env-supplied key (headless-without-systemd),
  otherwise clear (`DEVHARNESS_PANEL_SUBSCRIPTION=1` still accepted, now the default's name). The
  rev-0.4.0 overage fallback injects its key per-call via `options.env` — unaffected. **(2)** the
  job record said "check stderr" while the panel threw the stderr away — `BuildRunner._run` now
  appends `exc.stderr` (when the exception carries one, e.g. the SDK's ProcessError; capped 2000
  chars) to the job error, so the panel's error banner is not a dead end.
- **2026-07-14 rev 0.4.5.** **The leftover-env hole closed + the activity signal made honest.** The
  rev-0.4.4 default fix was live-defeated within minutes, twice, by two residuals — both fixed:
  **(1) a leftover `DEVHARNESS_DB` in a long-lived terminal** silently overrode the new default (the
  operator restarted per instructions and still got the stale store; env overriding is deliberate —
  the VPS pins its store — but a forgotten variable is indistinguishable from a chosen one). The
  panel now computes a **startup notice** when the env-named store is NOT the most recently active
  one ("store came from DEVHARNESS_DB (X) but Y has newer activity — leftover env var?"), surfaced
  as a UI warning banner via `/state.notice` (cleared on project switch; quiet when env pins the
  freshest — the VPS single-store case; measured BEFORE the panel opens the store, since the
  writer's own open would freshen an mtime-fallback store and suppress the warning — review catch).
  **(2) file mtime was the wrong activity signal:** merely opening/closing a WAL store checkpoints
  and bumps its mtime with zero events written — the panel itself laundered the legacy store's age
  this way (a switch away from it made it "the most recently written store" again). Ranking, the
  header age label, and the notice now all derive from **event activity**
  (`pstate.last_activity_millis`: the newest `*_at_millis` among the store's last 20 event
  payloads, mode=ro per sibling store, mtime only as fallback for empty stores) — and
  **future-dated values are ignored** (60s slack): a trust grant's `expires_at_millis`
  (granted+7d) is a schedule, not activity, and would have crowned a dead store "most recently
  active" for a week after any promotion (the adversarial review's live-verified catch — the same
  wrong-store class recurring inside the fix). Verified on the real stores: `devharness.db` reports
  its true last work (Jun 27) despite a today mtime; ranking picks `a private build.db`; the notice fires on
  the exact leftover-env scenario. Adversarial diff review (4 findings: the future-timestamp
  poisoning, the measure-before-open ordering, a test-branch gap, a cosmetic research-start label
  window — first three folded, the fourth accepted). Panel tests 13.
- **2026-07-14 rev 0.4.4.** **The panel never silently opens a stale store.** Launched without
  `DEVHARNESS_DB` (exactly per the run instructions), the panel opened the hardcoded legacy
  `var/devharness.db` — the June-era multi-project store — and greeted the operator with a dead
  csvlite plan's red ⚠ retry banner as the first thing on screen. Live-hit by the operator minutes
  after rev 0.4.3 shipped; the silent-wrong-default input class (rev 0.3.63's store-path hygiene,
  the a private build stale-target incident) recurring at the launch surface. Fixed: `serve()` with no
  explicit store falls to `_default_db()` — the most recently written `*.db` under the REPO's
  `var/` (anchored to the repo root like `cli/_bus.py`, NOT the CWD — the diff review caught that a
  CWD-relative scan would adopt any foreign `var/*.db` the panel is launched beside, the same class
  relocated; mtime is checkpoint-granular under WAL, sufficient for "last worked in"; a vanished
  file is skipped, not fatal), falling back to the fixed name under that root only when no store
  exists (first run — still created loud). An empty-string `DEVHARNESS_DB` now also falls through
  instead of resolving to the CWD. The VPS deploy pins an absolute `DEVHARNESS_DB` — unaffected.
  And stale data is now labeled on sight: `/state` carries `store_mtime_millis` and the header
  appends "· last activity Nd ago" when the store file is ≥1 day old (suppressed while busy — under
  WAL a just-started build keeps the stale mtime until its first checkpoint). Adversarial diff
  review (3 findings, all folded pre-commit). Carried defect candidates from the same session, not
  yet cycled: the Drive card's `tasks_by_state` chips count the WHOLE store while the task rows show
  the current plan (scope mismatch reads as contradiction), and a deliberately-abandoned rejected
  task keeps the ⚠ retry hint red forever (no operator-accepted-terminal concept).
- **2026-07-14 rev 0.4.3.** **Web-panel friction reduction — the mobile operator stops hand-typing
  what the harness already knows.** Reviewing the panel against the standing goal (every operator
  surface is a harness test; friction is a defect) found five classes, all fixed in one pass, each
  UI-only or additive (`/state`/`/events` gain fields; no new event type, no migration, EVENT_TYPES
  stays 62): **(1) tappable task list** — `/state` gains `tasks` (ordered rows: `task_id`,
  truncated `description`, `outcome`, blocked-row `reason`, `buildable`, `certifiable`), rendered as
  rows with contextual Build/Retry/Certify/Integrate buttons, replacing the counts-only chips + the
  hand-typed `task_id` field (kept only as a collapsed "advanced" input for tasks outside the current
  plan). The design's adversarial review mandated two guards that shipped with it: **Build is
  withheld unless every declared dependency is `completed`** (`ConsoleDeveloper._select_task` does no
  dependency-order validation on an explicit task_id, so a one-tap out-of-order dispatch would build
  against a tree missing its dependencies' code and poison assemble), and **`certifiable` is computed
  only when idle** (mid-dispatch it flickers true between the verifier pass and the loop's own
  certification — a glowing decoy); `certifiable` mirrors `ConsoleReview.certify`'s admission
  preconditions exactly (started + lifecycle non-terminal + verifier pass in the current attempt), so
  a shown button cannot 400. A certifiable row hides Build (re-dispatch would discard the verifier
  pass). **(2) Spec viewer + confirm-sign** — the `/spec/review/{id}` route existed with NO UI; the
  operator signed the governance gate blind from the phone. `/state` gains `unsigned_spec_id`; a
  View-spec overlay renders the drafted spec per-field and its Sign/Reject act on the VIEWED spec_id
  (TOCTOU guard — a bare sign takes whatever is latest-unsigned at POST time); Sign confirms.
  **(3) Readable progress log** — the TUI's `_PROGRESS_EVENTS`/`_frame_line` extracted to shared
  `console/progress.py` (no Textual import — the panel host may lack it; drift-guarded by test);
  `/events` rows gain `line` (salient payload fields for progress events, bare type otherwise) so the
  log shows `verifier_outcome task_id=t3 passed=True` instead of an opaque event-type wall.
  **(4) State-aware buttons** — the hint machine now returns a machine token too
  (`_hint_and_action`; `/state` gains `next_action`: busy·answer·sign·research·plan·retry·target·
  build·assemble·done; hint strings byte-identical, review-verified): while busy every action button
  disables EXCEPT Cancel and Answer (research parks busy on its question — the verified-safe
  answer-while-busy path; a `busy` token there would grey out the only live button, so `answer` wins,
  tested), spec buttons disable without an unsigned spec, and the button matching `next_action`
  glows. Also fixed: `post_dispatch` refused when the SESSION target was unset even though
  `DEVHARNESS_TARGET_REPO` was set and honored by `ConsoleDeveloper` (and by the hint) — the route
  now matches the TUI's condition, ending the hint-says-build/route-refuses drift. **(5) structured
  new-project form** — the `name | repo_path | seed` pipe-syntax single field (the stale-re-entry
  input class behind the a private build-into-a private build incident) becomes three fields; the POST already
  took them separately. **Injection posture:** task descriptions/reasons and spec fields are
  LLM-derived text — every new render path is DOM-built (`createElement`/`textContent`); the diff
  review confirmed zero `innerHTML` remains in the panel (the rev-0.3.44 untrusted-text class).
  Known-and-accepted: `certifiable`'s per-poll event scans (bounded — computed only when idle, only
  for started non-terminal rows; flagged for indexing if stores grow), all blocked rows' Retry glow
  on `retry` (the hint names the first). Two adversarial reviews (design + staged diff, both against
  real source); findings folded pre-commit. Panel tests 10 (task rows, next_action machine incl.
  answer-over-busy, snapshot fields, `/events` line, shared-module no-Textual guard).
- **2026-07-08 rev 0.4.2.** **`cost_spent` carries the billing model — tier routing becomes
  telemetry-verifiable.** The a private build tier-validation drives could prove the T0–T3 routing only by reading
  code: the event had no model field, and the `verify_review` emission SUMMED two clients running
  different models (T1 sonnet-5 verifier + frontier reviewer, rev 0.3.84), so a misrouted verifier
  silently billing frontier was indistinguishable from a normal expensive reviewer. Changes: `CostSpent`
  gains `model: str = ""` (the realized fact, deliberately not `tier` — lossy, and the mapping can change;
  the rev-0.4.0 overage fallback keeps it accurate since an API-key rebill doesn't change the model); the
  four verify_review sum-sites (console dispatch/OSS + both script drivers) route through ONE shared
  `emit_client_costs` helper — one emission per DISTINCT client, each with ITS model (identity-deduped, so
  the injected-single-client test posture still emits once; the console dispatch site stays pinned BEFORE
  the terminal-abort block, preserving event order vs `terminal_outcome` for the retro `preceding_events`
  windows); the eight single-client emitters pass their model; and the plan's adversarial review found a
  **missed spender** — the standalone certify action (`console/review.py`, TUI `C` / panel `/certify`)
  billed a fresh frontier reviewer with NO `cost_spent` at all (a pre-existing SC-6 hole on the
  blocked-plan recovery path) — now emitted via the same helper. No migration, no new event type, no
  projection change (`proj_cost` stays role-keyed; commitment 5 — the events ARE the telemetry); the
  console `$` viewer lists per role·model from raw events (guard + TOTAL stay on proj_cost; pre-0.4.2
  events render `—`), the dashboard CostTile keys by role·model (caption corrected to its real source),
  the panel stays per-role deliberately. SC-6 reworded to the per-client contract. Validation: a
  post-drive `SELECT role, model, SUM(amount_usd) … GROUP BY 1,2` makes an advisory role billing a
  frontier model a misroute on sight. 4 tests added/extended.
- **2026-07-08 rev 0.4.1.** **External-target commit subjects carry the task's REAL class.** Both scratch-
  branch commit sites (`console/developer.py` and the `scripts/run_developer.py` parity twin — the same
  console/script pair as rev 0.3.71) hardcoded `devharness feature <task_id>: …`, so every certified
  bugfix/refactor/dependency_bump landed **git-labeled "feature"** while the event log carried the true
  class — surfaced by the a private build tier-validation drives (the bugfix + refactor commits both read `feature`).
  Fixed with ONE shared helper (`scratch_commit_subject(planned_task)` in `console/developer.py`, imported
  by the script — no re-hardcode possible) using `planned_task.task_class` (`or "task"` for a decoder-legal
  empty class). Verified no consumer parses the subject anywhere (assemble + the rev-0.3.61 contamination
  guard key on branch NAMES; the OSS identity tests read `%an`/`%cn`); the OSS `devharness OSS contribution`
  subject and the `devharness checkpoint` label are distinct, correct, and untouched; history in existing
  artifact repos keeps its old labels (forward-only, log never rewritten). Adversarial review: SHIP, 1 LOW +
  2 NITs (the parity-tripwire presence assertions, folded). 2 tests (subject-per-class + console/script
  share-the-helper guard); 1524 runtime green.
- **2026-07-06 rev 0.4.0.** **Overage auth-fallback — fable-5 (and any model) keeps working when its weekly
  subscription quota is exhausted, by transparently rebilling that call on the API key.** The harness runs
  the SDK on the operator's claude.ai subscription (`ANTHROPIC_API_KEY` popped at startup). When the
  operator's **weekly Fable-5 quota hit 100%**, every `claude-fable-5` call (director reasoning, the
  developer writer) crashed with a bare `Command failed with exit code 1` — a **quota/credit rejection**,
  not "model unavailable" (the earlier rev-0.3.99 preflight, which mislabeled it and printed a startup
  "Fatal" line, was reverted). **Corrected by direct-CLI + SDK research** (an earlier "the key only serves
  fable-5" conclusion was a flaky-multi-query-in-one-process SDK-test artifact, disproven by the direct
  CLI): the subscription returns a clean `"You're out of usage credits"`, the SDK yields a **structured
  `RateLimitEvent(status="rejected")`** (and/or an `AssistantMessage(error="billing_error")`) *before* it
  raises, and the operator's **API key serves every model** (direct CLI + `/v1/messages` both succeed).
  `ClaudeAgentOptions.env` injects a key **per-subprocess** without mutating global `os.environ`. The fix
  (`runtime/devharness/sdk_query.py` `run_query`, wrapping the four SDK message loops — `mcp/base._run`,
  `roles/developer`/`discovery`/`scope_resolver`): buffer the attempt; on a **weekly/overage** credit
  exhaustion **and only then** (NOT a transient `five_hour` cooldown — reviewer F2) **and** with no prior
  tool use (so a mid-session rejection never re-drives a dirtied worktree — reviewer F11), retry once with
  the valid key (sourced from the **top-level** `~/.claude.json` `mcp-reasoning`/`parallax` server, exactly
  as the director already reads it — reviewer F4) injected via `options.env`; every other error surfaces
  unchanged; the auth-switch is surfaced with a stderr line (no new event — the crash path has no bus,
  reviewer F1/F3). It is **per-call, so it auto-reverts to the subscription when the weekly quota resets**
  (reviewer F8). Not a model swap (fable-5 stays), not error-hiding (only the credit-rejection triggers it,
  matching the existing `TRANSIENT_SDK_RESULT` "retry only the specific signal" discipline), no probe, no
  `models.py`/tier change, no model-id literal. Research → plan → adversarial review (5 findings folded) →
  implement. **Live-verified end-to-end**: with fable-5 out of subscription credits, the console director
  plan completes a 5-task decomposition on fable-5 via the fallback (8 rebills), no crash. 8 unit tests;
  1522 runtime green. Known residue: the SDK still prints its own `Fatal error in message reader` on each
  subscription-rejected attempt before the helper catches it (the clean `⚠ … billed via the API key` line
  follows each) — left visible rather than fd-suppressed (fd suppression can hide real stderr).
- **2026-07-05 rev 0.3.98.** **The `test_coverage` verifier axis is language-aware — the first step of
  making the loop non-Python-drivable.** All eight real builds were stdlib-only Python CLIs; the explore
  parsers are polyglot but nothing downstream consumed them, so a Rust/JS/Go project could not complete
  the loop. **An adversarial review reshaped the change**: the first design auto-derived the test command
  from the explore pass's detected framework, but `run_and_emit` (the only writer of the `explore_pass`
  artifact) has NO runtime caller — research/promote/discovery all call `run` in-memory — so no artifact
  exists to read, and for a *scaffold* the repo doesn't exist yet, so the framework is undetectable in
  principle. The auto-derivation was dropped; the already-working path needs no code — the operator sets
  the test command on the build target (`T`), and it threads to the scaffold verifier, the feature
  `test_suite`/`test_coverage` axes, and the worker self-test. What remained were two real, load-bearing
  blockers a Rust `feature` hits: **(1)** `feature_spec_claim`'s `test_coverage` axis (run on EVERY feature
  task) required a Python `def test_…`/`class …Test…` line inside a `test_*.py`/`tests/` path, so a Rust
  `#[test]` yielded no coverage → the feature was rejected; `_test_coverage.py` now dispatches the
  language from `test_command[0]` (`cargo`→rust, `go`→go, `npx`/`npm`→js, else python) and detects Rust
  by the `#[test]`/`#[tokio::test]`/`#[rstest]` attribute line in ANY `.rs` file (no test-path gate —
  idiomatic Rust unit tests live in `#[cfg(test)] mod tests` inside `src/*.rs`; the regex is verified NOT
  to match the `#[cfg(test)]` module marker), plus JS (`it(`/`it.only(`/`test(` in `.test`/`.spec` files) and Go
  (`func Test…` in `_test.go`); Python behaviour is byte-unchanged (default). **(2)** `cargo test` creates
  `target/` as exhaust exactly as pytest creates `__pycache__`, tripping the realized-diff scope check on
  a repo without a matching `.gitignore` (the rev-0.3.58 failure class, one language over) —
  `worktree/hygiene.py` now purges `target` too, but under a stricter rule than the caches (deleted only
  when UNTRACKED, never restored-to-HEAD), so a legitimately-tracked dir named `target` and any in-scope
  edit under it are left intact; `node_modules` is deliberately NOT purged (it holds installed deps —
  deferred to a JS drive). **An adversarial code review of the implementation** caught the Windows
  `cargo.exe`/`npm.cmd` head not stripping its extension (→ silent misdiagnosed pytest fallback), the JS
  chained-form false-negative, and the any-depth tracked-source revert risk — all three fixed before
  commit. Deferred to when they're driven (each its own cycle): `regression_command`/`pass_fail_command`
  for non-Python bugfix/refactor (the `cargo test` per-test-output problem, with a latent vacuous-pass
  risk in the existing env-override path) and `derive_bump_fields` for cargo/npm dependency_bump. No new
  event/migration/regen. 1514 runtime green (+11 test_coverage language/edge cases + hygiene build-dir cases).
- **2026-07-05 rev 0.3.97.** **`emit_sync` is now an atomic append — the hash-chain fork risk every prior
  review routed around is closed at the source.** `emit_sync` read the tail hash (`_last_hash`, a bare
  SELECT) then INSERTed with that `prev_hash` under **no write lock**, so two writers on one store (two
  processes / threads — e.g. `devharness sign`/`answer` opening their own connection to a `var/*.db` while
  the console holds it) both read the same tail and append → a permanent chain fork `verify_chain` can only
  detect, never undo. The single-writer lock (Inv 1) is a *projection* lock, not a sqlite lock. Fix: take
  the sqlite write lock BEFORE the tail read via an explicit **`BEGIN IMMEDIATE`** (default `isolation_level=""`
  — mechanism (a); (b) `isolation_level=None` was rejected because autocommit breaks `parity.py` `rebuild`'s
  atomic clear-and-replay → Inv-8 breach), held through the INSERT + handlers + `commit`. Begin only when no
  transaction is already open (`in_transaction`): a caller that did a related direct-DML WRITE first (the
  artifacts batch) already holds the write lock, so its tail-read is race-free and a manual BEGIN would
  double-begin — the unconditional commit still commits that whole batch (Inv-8 parity preserved). The
  **explicit `rollback()` on any exception is load-bearing** — the connection is shared, so a mid-emit
  handler raise must undo the batch AND clear the transaction, or the next `emit_sync` inherits a poisoned
  open transaction ("cannot start a transaction within a transaction"). Adversarially reviewed on the
  transaction mechanism + every implicit-batching caller. `tests/runtime/test_bus_concurrency.py`: a
  barrier'd N-thread tripwire (proven to fork `verify_chain` on a temporary revert of the BEGIN, intact
  with it) + a rollback-correctness test (a raising handler → event not persisted, `in_transaction` False,
  the next emit on the same conn succeeds) + serial-chain. No new event/migration/regen. 1503 runtime green.
- **2026-07-05 rev 0.3.96.** **`devharness backfill <store>` — the first real closed-loop run on real data,
  on a scratch COPY.** The eight real stores predate the monitor (rev 0.3.87), so the signal-retro loop had
  never run on real data. Backfill snapshots a store, runs the monitor sweep (emit `invariant_violated`) +
  the signal-retro drain (create gate-change candidates) on the COPY, and never writes the original. **Two
  adversarial reviews reshaped it from the naive "write into the original" design**, which was both (1)
  UNSAFE — `emit_sync` reads the tail hash then appends with no `BEGIN IMMEDIATE`, so an out-of-process
  writer forks the chain (Inv-7 breach), and the `proj_lock` guard is porous (held only during an active
  dispatch, not a whole console session) — and (2) BROKEN — the orphan being backfilled leaves a
  non-terminal `proj_task_lifecycle` row that makes `fermata.is_held` True, so the drain no-ops and produces
  0 candidates on the exact target. Parallax chose the copy design (82, over drop 63 / write-original 38).
  The copy resolves BOTH: safety (the original is opened `mode=ro` + snapshotted via the sqlite backup API —
  the corruption path is eliminated, not guarded), and correctness (the drain runs with a `QuiescentFermata`
  — a frozen snapshot is offline analysis, not a live build, so a historical orphan no longer blocks it).
  Live-verified end-to-end: `backfill var/a private build.db` → **1 signal → 1 reviewable gate-change candidate** on
  the copy (the first real closed-loop run), `a private build.db` byte-unchanged; `a private build` → 0. `cli/backfill.py`
  + `"backfill"` in `_SUBCOMMANDS`; 5 tests incl. the mandatory orphan case (a non-orphan seed would pass
  while the real path fails). Reuses `run_invariant_sweep` + `SignalRetroScheduler` verbatim, so the copy's
  candidates are identical to a live post-monitor build's. No new event/migration. 1500 runtime green.
- **2026-07-05 rev 0.3.95.** **Golden regression guard for the invariant-monitor checks (test-only) — locks
  in the rev-0.3.93 re-drive fix.** The Inv-10/Inv-5 re-drive blind spots shipped because the tests only
  exercised trivial single-attempt shapes. `tests/runtime/test_monitor_golden.py` builds one fixture
  reproducing the exact real-`var/*.db` multi-attempt patterns that the pre-0.3.93 naive checks
  false-flagged — `rejected×4→completed` (pgharness-disc-t0), `rejected→rejected` (csvlite-t2),
  `aborted→start→completed` (r1-t2), `start,start,earn,completed` (transient retry), the pgharness-val2
  earned-in-attempt-2-despite-later-failure Inv-5 case — plus a genuine double-terminal, a trailing orphan,
  and an unearned completion, and asserts `all_violations` reports **EXACTLY** `{(10,F),(10,G),(5,H)}` and
  nothing else (equality, so a new false positive OR a missed genuine violation both fail). Verified as a
  real tripwire: temporarily removing the `tiw`-reset hinge (re-implementing the bug) fails it loudly;
  restoring passes. In `tests/runtime` → auto-CI (no workflow change); reuses `all_violations` verbatim (+ a
  `devharness sweep` CLI pass over a file copy) so it can't drift from the live monitor. No production
  change/event/migration. 1495 runtime green. This closes the monitor arc: monitor (0.3.87) → fault-injection
  (0.3.88) → learning-loop closure (0.3.91) → re-drive fix (0.3.93) → sweep CLI (0.3.94) → regression guard.
- **2026-07-05 rev 0.3.94.** **`devharness sweep <store>` — the retroactive invariant-sweep as a read-only
  operator diagnostic.** The ad-hoc read-only sweep (running the monitor's checks over an existing store's
  whole event log) was the session's most productive technique — it found the rev-0.3.93 monitor re-drive
  blind spots and confirmed the 13 real stores are invariant-clean but for one genuine orphan. This makes it
  repeatable: `python -m devharness sweep <store>` runs `monitor.checks.all_violations` (all 7
  stream-checkable invariants: 1/5/7/9/10/12/17) over any store and prints a grouped report — exit 0 clean,
  1 violations found, 2 usage/unreadable/too-old. **Strictly read-only** (adversarial review corrected the
  first draft): it opens the store `mode=ro` (a stray write is impossible), **never** routes through
  `open_store`'s `migrate` (which would write a schema-behind store and crash on a newer one), **never**
  creates a missing store, and has **no `--emit`** (persisting is `run_maintenance`'s job — an out-of-process
  writer with `emit_sync`'s non-atomic read-then-append could fork the hash chain against a live store, an
  Inv-7 breach). Reuses `all_violations` verbatim so the CLI and the live monitor can never diverge. New
  `cli/sweep.py` + `"sweep"` in `_SUBCOMMANDS`; 6 tests incl. a not-mutated assertion; live-verified against
  the real stores (a private build → the one orphan; dedup → clean; both byte-unchanged). No new event/migration.
  1493 runtime green.
- **2026-07-05 rev 0.3.93.** **Live invariant monitor re-drive blind spots — two task-lifecycle checks
  false-flagged the harness's own re-drive model (found by running the spine on real data).** Parallax's
  "run the §S7 spine on real accumulated data" surfaced that the monitor never ran over the real console
  stores (they predate rev 0.3.87); running its checks RETROACTIVELY over the 13 `var/*.db` stores exposed
  a latent bug: `check_terminal_per_task` (Inv 10) counts terminals per `task_id` (`len(lst) > 1`) and
  `check_done_earned` (Inv 5) reuses the live `can_complete(task_id)` (which reads the LATEST attempt) — but
  a task legitimately gets MULTIPLE terminals + `task_started`s (the operator re-drives a rejected task —
  the retro dedup is keyed on `(task_id, terminal_kind)` for exactly this — and the bounded auto-retry
  re-runs within a dispatch). Retroactive sweep: **18 Inv-10 false flags + 1 Inv-5** across the stores (e.g.
  `pgharness-disc-t0` = rejected×4→completed; `pgharness-val2-t0` completed-in-attempt-2 flagged because
  attempt-3 failed). Latent only because no real re-driven build had run with the monitor active — the next
  one would have emitted spurious `invariant_violated` → (via the rev-0.3.91 signal-retro closure) spurious
  gate-change candidates flooding the review queue. **Fix (both checks attempt-aware):** Inv 10 → a
  seq-ordered PER-TASK "terminal-in-window" walk where a `task_started` RESETS the in-window flag (the hinge
  that keeps `start,term,start,term` clean while `start,term,term` flags); the orphan/liveness half stays
  gated on `include_orphans`/`_lock_held` and now also catches a re-driven task whose LATEST attempt
  orphaned (a new true-positive the old `terminated = set(terms)` missed). Inv 5 → scope the verifier-pass +
  reviewer-cert check to the completed terminal's OWN attempt window (its preceding `task_started` → the
  terminal), with a `-1` log-start fallback matching `can_complete`. `can_complete` itself is untouched (its
  live-completion use was correct; only the monitor's retrospective reuse was wrong). **Validated on real
  data:** 18 → 0 double-terminal + 1 genuine orphan (an abandoned research task); 1 → 0 Inv-5. Two
  adversarial-review passes confirmed the design + the two must-honor constraints (per-task keying; the
  trailing-orphan branch through the lock gate) + the fault-injection oracle (`transient_sdk_glitch`'s
  `start,start,…,completed` shape stays `handled`). 8 new monitor tests; no new event/migration; 1487
  runtime green. The green monitor tests missed it — they only exercised single-attempt shapes.
- **2026-07-05 rev 0.3.92.** **Signal-retro (rev 0.3.91) adversarial-review remediation — one confirmed
  behaviour bug + two hardening fixes the green tests missed.** A fresh-context review confirmed a real
  defect: the two new T0 signatures were registered GLOBALLY, and `match_signatures` runs every signature
  against every context, so the **terminal-triggered** `RetroScheduler` also fired
  `monitor_invariant_violated` whenever an `invariant_violated` sat in a **re-driven** terminal's
  `preceding_events` (build X rejected → monitor emits `invariant_violated` corr X → operator re-drives →
  completed; the completed terminal's preceding set over corr X includes it) → a **duplicate +
  wrongly-attributed** candidate on top of the signal path's. Fixed by **signal-gating** the two predicates
  on `not ctx.terminal_outcome_event` (the signal path builds it `{}`; the terminal path fills it), + a
  guard test. Two hardening follow-ups: an **open-candidate guard** in `SignalRetroScheduler` (skip
  emitting when a `pending` candidate already exists for the signal's `target_gate` — collapses a
  persistently-regressing fault's per-window candidates into one open review item and closes the
  crash-between-emits duplicate window; still ledgers the signal), and a **populated Inv-8 rebuild-parity
  test** for `proj_signal_retro_runs` (the generic check only exercised it empty). The `#4` silent-consume
  path (a future `_SIGNAL_EVENT_TYPES` entry without a matching signature) is documented in-code, not
  reachable today. No new event/migration; Inv 12 still preserved. 1479 runtime green; live re-drive
  verified (exactly one candidate, no terminal-path duplicate). The review found what the 5 green feature
  tests missed — they all built `terminal_outcome_event={}` and never drove the re-drive path.
- **2026-07-04 rev 0.3.91.** **Learning-loop closure: the monitor + fault-injection signals now become
  operator-review CANDIDATEs (EVENT_TYPES +1, migration 0028, no new invariant).** `invariant_violated`
  (rev 0.3.87 monitor) and `fault_handling_regression` (rev 0.3.88 loop fault-injection) were surfaced but
  the §S7 retro half was inert for them — a caught breach/regression was shown, never LEARNED from.
  Exploration showed why the existing T0 path could not reach them: the retro spine is
  `terminal_outcome`-triggered and its predicates scan a terminal's `preceding_events`
  (`correlation_id = terminal cid AND seq < terminal`), but `fault_handling_regression` has correlation
  `"fault-injection"` with **no live terminal at all** (the hermetic terminal stays in the throwaway
  store) and `invariant_violated` is always emitted at a **higher seq than its terminal** (often
  correlation `"monitor"`). Fix: a new **`SignalRetroScheduler`** (`retro/signal_scheduler.py`) drains the
  two event types directly, builds a `RetroContext` carrying the signal event, and reuses
  `RetroEngine.analyze` (T0-only) + two new `t0_matcher` signatures (`monitor_invariant_violated`,
  `loop_fault_regression`) → an **advisory `gate_change_candidate`** (`change_kind="tighten"`, a **non-core
  `target_gate`** — the Inv-12 validator never auto-rejects it and only `add_signature` auto-enacts, so it
  stays `pending` for operator review; the specific invariant#/fault detail is reachable via
  `evidence_event_ids`). Dedup ledger `proj_signal_retro_runs` (migration 0028, PK = the signal's own
  `event_id`, no AUTOINCREMENT — Inv-8 parity) + `signal_retro_run` event. Wired into
  `run_maintenance.drive()` after the sweep + loop-fault step (fermata-gated drain). Parallax picked this
  as the next item (82–85) and settled the candidate kind (gate_change/tighten 78 over a new queue 52 /
  antibody 18). No core gate can be weakened (Inv 12 preserved). 1476 runtime + 8 sidecar green; svelte
  clean. Known v1 limitation: `change_details` is a generic template (specifics via evidence), not inlined.
- **2026-07-04 rev 0.3.90.** **The adversarial self-tester had the same per-process gap — now fixed
  (correcting the rev-0.3.89 note that wrongly deferred it).** rev 0.3.89 recorded that the adversarial
  scheduler shared the loop-fault per-process reset (a fresh `AdversarialScheduler` each `drive()` call →
  its round-robin cursor reset every invocation → only the FIRST of the 13 gate probes ever ran in
  production, so 12 gate regressions were never checked) and left it "unchanged, a known residual." That
  was wrong: it is a real defect, not an optional revisit. `AdversarialScheduler.step` now runs
  `run_all_probes` (the whole probe set) per window, still fermata-gated. Unlike loop-fault (each probe is
  a costly hermetic build, so all-six-per-window is a real cost tradeoff), gate probes are pure
  microsecond `gate.check` calls — running all 13 every window is free, so there is no tradeoff to weigh.
  1471 runtime + 8 sidecar green.
- **2026-07-04 rev 0.3.89.** **Loop fault-injection runs the WHOLE probe set per maintenance window (a
  production-wiring gap the rev-0.3.88 live validation surfaced).** Two validations were run against the
  shipped feature: a **deliberate-regression drill** (revert the real rev-0.3.86 `crash→abort` fix on a
  throwaway branch → the `mid_dispatch_crash` probe fired a genuine `fault_handling_regression`, Inv 10 —
  proving the oracle catches a real regression, not just the monkeypatch) and a **live maintenance-window
  run** (`run_maintenance.drive` against a scratch store → `loop_fault_ran=True`, the live log carried
  ONLY the result event with no synthetic build events leaked, all six probes handled, temp dirs cleaned).
  The live run exposed that `main()` invokes `drive()` **once per process** (cron-style) and `drive()`
  constructs a fresh `LoopFaultScheduler` each call, so the rev-0.3.88 round-robin cursor **reset every
  invocation and only ever ran the first probe** (`mid_dispatch_crash`) in production — the other five
  fault classes never executed in a real window. Fix: `LoopFaultScheduler.step` now runs
  `run_all_loop_faults` (the whole probe set) per window, still fermata-gated, dropping the per-call
  cursor. Cost: ~6 hermetic builds (`git init` + worktree + a verifier subprocess each) per maintenance
  pass, bounded by the fermata — the operator's deliberate choice over the cheaper event-log-rotation
  alternative. **The adversarial self-tester has the IDENTICAL per-process gap** (its cursor also resets,
  so only its first gate probe runs per window); left unchanged by operator decision — noted here as a
  known residual. No new event, no new tile, no new invariant; 1471 runtime + 8 sidecar green.
- **2026-07-03 rev 0.3.88.** **Loop fault-injection — the adversarial self-tester extended from gates to
  the whole loop (EVENT_TYPES +2, no new tile, no new invariant).** The rev-0.3.87 monitor made silent
  failures loud *when they happen in a real build*; this closes the loop by **deliberately injecting the
  failure classes that hurt this session** — a mid-dispatch worker crash, a git-128 checkpoint, a
  hard/transient SDK error, a missing test runner, a worktree collision — into a **hermetic build** (a
  throwaway in-memory store + temp git repo, never the operator's live log) and asserting the harness
  handles each gracefully. `runtime/devharness/faultinjection/`: `hermetic.py` (`hermetic_build` packages
  the console-developer test scaffold as RUNTIME code — the runtime must never import from `tests/`),
  `probes.py` (six `LoopFaultProbe`s, each injecting at an existing developer seam —
  `write_hook`/`checkpoint_fn`/`query_fn`/`worktree_factory` — round-robin registry like the adversarial
  probes), `runner.py` (`run_loop_fault`), `scheduler.py` (`LoopFaultScheduler`, fermata-gated,
  one-probe-per-window). **The oracle is `run_invariant_sweep` (feature A):** a fault the harness turns
  into one clean terminal emits NO `invariant_violated`; a fault that silently orphans the task fires an
  Inv-10 breach — so a *fault-handling regression* = the sweep fires. These probes therefore **lock in
  the rev-0.3.86 fixes** (#4 crash→abort, #6 identity fallback, #7 transient retry): a future change that
  regresses them is caught by the probe's own sweep. **Two review subtleties (adversarial pass, folded
  in before build):** (1) the oracle **COUNTS `invariant_violated` events** in the hermetic store rather
  than reading `run_invariant_sweep`'s return value — `ConsoleDeveloper.dispatch` already sweeps + dedups
  internally, so a second sweep returns `[]` for any dispatch that returned (even one returning a bad
  terminal); the runner still calls the sweep first to flush the one case dispatch's internal sweep can't
  reach (dispatch *raised* before its integrate/sweep line, leaving a live orphan). (2) cleanup removes
  the whole `mkdtemp` root — the dispatch's worktree pool lives at `<root>/.devharness-worktrees/…`
  inside it — with a Windows-robust `rmtree` (read-only git objects). New events `loop_fault_run` +
  `fault_handling_regression` (audit-only, no projection); wired into `run_maintenance.drive` beside the
  adversarial probe (fermata-gated); surfaced on the existing Adversarial self-tester tile (SSE-fed) + a
  `/diag` line — no new tile, so no C7 change. 11 tests (6 handled probes + the post-`task_started`
  regression proof + the round-robin/fermata scheduler); 1471 runtime + 8 sidecar green. Follow-up (B2):
  per-class expected-terminal assertions once the monitor-only oracle proves out.
- **2026-07-03 rev 0.3.87.** **Live invariant monitor — the 18 invariants become live behavioral guards
  (§S9 tile 27→28, EVENT_TYPES +1).** The 18 invariants were enforced only at test time (structure); the
  worst defect of the first real panel-driven build was *silent* — a `task_started` with no
  `terminal_outcome` that looped invisibly (a live Inv-10 breach a green unit test cannot catch). This
  feature turns the **7 behaviorally-checkable invariants** (1 single-writer, 5 done-earned-twice, 7
  hash-chain, 9 correlation coverage, 10 exactly-one-terminal, 12 core-gates-unweakable, 17
  verified-before-trusted) into live guards. `runtime/devharness/monitor/` — `checks.py` (each check
  reuses the canonical helper: `verify_chain`, `can_complete`, `would_weaken_core_gate`, a
  `proj_lock`-gated orphan scan, …) + `sweep.run_invariant_sweep`, which sweeps the log and emits a new
  `invariant_violated` event for each NEW breach (idempotent via a `dedup_key`). Emitted at **top level**
  (never from a projection handler — that would re-enter `emit_sync` mid-transaction and corrupt the
  chain), so it's the established observe→emit pattern. **Key subtlety:** the boot check
  `check_terminal_outcome_required_per_task` misses the #4 orphan (a crashed dispatch leaves the task
  stuck in `running`), so the monitor flags any started-without-terminal task gated on **no write lock
  held** (the non-circular quiescence signal — the lock releases even on a crash; `fermata.is_held` would
  be tripped by the orphan itself). Wired into `ConsoleDeveloper.dispatch` (after integrate — covers the
  panel + TUI) and `run_maintenance.drive` (the script path); advisory, never breaks a build. Surfaced on
  a new `invariant_monitor` dashboard tile, the panel `/diag` bundle + `/state` count + a red header
  indicator. Parallax ranked it #1 (88) among issue-finding features; it's the oracle for a later
  fault-injection feature. No NEW invariant (it monitors the existing 18). 9 monitor tests incl. the #4
  orphan regression + the lock-held skip + dedup + no-feedback-loop; 1460 runtime + 8 sidecar green.
  Follow-up: a retro `_invariant_violated` T0 predicate → auto CANDIDATE.
- **2026-07-03 rev 0.3.86.** **Two harness defects the first real panel-driven build surfaced — fixed
  through the full cycle.** The first end-to-end build driven from the web control panel on the VPS
  (a private build, 5 tasks, completed + assembled) exposed two behaviour bugs a green suite never caught.
  **(1) A crashed dispatch emitted no terminal → a silent "looping on N".** `ConsoleDeveloper.dispatch`
  ran the developer in a retry loop but a *hard* crash mid-dispatch (a missing git identity, `python`
  not found on Ubuntu, an SDK error) propagated out with no `terminal_outcome` — the task started
  (`task_started`) yet never terminated (an **Inv 10** violation), so it stayed pending and the loop
  re-dispatched it forever with no visible cause. Fixed: the dispatch now catches a mid-dispatch crash
  and, when no terminal was emitted, forces an `aborted` terminal via the existing
  `done_is_earned.abort` (valid from any state) — the task reaches exactly one terminal (Inv 10), the
  plan blocks, and the `→ next` hint surfaces the explicit retry command instead of looping.
  **(2) Research re-asked a resolved divergence.** The interview's only defence against re-asking was
  threading prior Q&A into `elicit`'s context and hoping it wouldn't repeat; live, `elicit` re-surfaced
  the same "collapse repeated hyphens" point **3× (reworded each time)**, so an exact-match dedup would
  miss it. Added a deterministic re-ask backstop (parallax `decide`, B 82 over a semantic call / exact
  match / context-only): a Jaccard overlap over each divergence's **question + its `signal` field**
  (the signal references the same spec clauses across rewordings, so it's the stabler anchor); once the
  min-questions floor is met, a round overlapping an answered one ≥ 0.5 stops the interview. Deterministic,
  no added per-round LLM call, bounded by the min floor + the sign-off gate. Both fixed + regression-tested
  (`test_dispatch_crash_emits_aborted_terminal_not_silent_loop`, `test_reask_of_an_answered_divergence_stops_the_interview`;
  two fixed-payload interview tests updated to distinct-per-round questions). Four further fixes the
  same build surfaced, all done + tested: **(3)** the checkpoint commit + the assemble merge fall back to
  an inline git identity only when the repo configures none (the `git commit` exit-128 crash on a box
  without a global identity), preserving the operator's when present; **(4)** the intermittent SDK
  glitch `Claude Code returned an error result: success` (`is_error` with a contradictory `success`
  subtype — it failed the director twice before succeeding) is now retried by the director's plan + the
  developer's dispatch (a non-transient error still propagates); **(5)** the panel's progress log no
  longer double-renders (self-scheduled polling + a per-event dedup guard); and **(6)** the deployment
  gaps are folded into `deploy/vps/bootstrap.sh` (`python-is-python3` + pytest, a global git identity,
  the headless-API-key auth model) so a fresh VPS deploy needs no manual fixes. Also new this session:
  the **web control panel** (`runtime/devharness/panel/` — a stdlib `http.server` front over the console
  action layer, single-writer-serialized, with a self-contained mobile UI + a one-tap `/diag` "Copy for
  Claude" bundle) and its **VPS deployment** (systemd + Caddy behind a path prefix, `deploy/vps/`). 1451 runtime green.
- **2026-07-02 rev 0.3.85.** **The OSS writer is now tier-routed too (operator request; no invariant
  change).** Rev 0.3.84 routed the writer by class tier on the console + `run_developer` paths but
  left the OSS writer on frontier, because an OSS run dispatches a whole batch of `is_oss` tasks under
  ONE `developer_kwargs` (unlike the console's one-task-per-dispatch). New helper
  `task_classes/registry.batch_writer_tier(class_names)` picks the **highest** class tier across the
  batch — so a single-class batch (the common case) routes correctly (a bugfix/bump contribution
  writes on `claude-sonnet-5`), while a mixed batch takes the frontier tier and never downgrades a
  T2 task. Wired into `console/oss.py` and `run_oss.py` (`dev_kwargs["model"] =
  model_for_tier(batch_writer_tier(...))`, live-only). The OSS verifier/reviewer split from 0.3.84 is
  unchanged. 1439 runtime green.
- **2026-07-02 rev 0.3.84.** **Router widened per two operator decisions — cheaper writes on the two
  mechanical classes + the first-pass verifier on T1 (§S2/§S9 cost; no invariant change).** After
  0.3.82 shipped "Advisory only" and 0.3.83 raised `bugfix`/`dependency_bump` to ≥T2 (my call, which
  the operator corrected), the operator chose the more aggressive cost posture on both open questions.
  **(1) Cheaper writes:** `bugfix`/`dependency_bump` restored to ≥T1 (spec table + `builtin.py`), and
  the WRITER is now routed by its class tier — the console dispatch + `run_developer` thread
  `dev_kwargs["model"] = model_for_tier(class.tier_minimum)`, so a bugfix/bump developer runs the
  cheaper `claude-sonnet-5` while `feature`/`refactor`/`new_project_scaffold` (T2) stay
  `claude-fable-5`. **(2) Verifier on T1:** the previously SHARED verifier+reviewer parallax client is
  SPLIT — `verifier_parallax = live_parallax_client(model=model_for_tier("T1"))` (the high-volume
  first-pass verifier + the dispatch-time non-goals check) and `reviewer_parallax =
  live_parallax_client()` (frontier), so the fresh-context reviewer remains the one guaranteed-frontier
  pass of "done earned twice." Applied to the console developer + OSS paths and both script drivers
  (`_make_complete_task`/`_build_harness`/`build_oss_harness` now take both clients; cost telemetry
  sums both without double-counting the injected-test same-object path). An adversarial review
  confirmed no reviewer landed on T1, no signature caller was missed, and only `bugfix`/`dependency_bump`
  downgrade. (The OSS *writer* stays frontier — outside this decision's scope; the verifier split still
  applies there.) Supersedes the 0.3.83 tier alignment. 1438 runtime green.
- **2026-07-02 rev 0.3.83.** **§S2 tier table realigned — `bugfix`/`dependency_bump` ≥T1 → ≥T2, matching
  the code and the writer-tier rule (no invariant change).** The rev-0.3.82 router surfaced that the
  §S2 table declared `bugfix`/`dependency_bump` at ≥T1 while `task_classes/builtin.py` enforced ≥T2 — a
  latent contradiction (the code's floor was stricter than the declared one). Resolved by amending the
  TABLE up to ≥T2: both are BUILD classes that dispatch the developer (the single writer) to write code,
  and the governing rule is "the single writer runs at T2–T3," so a bugfix/bump write floors at the
  writer tier, not the advisory T1. The original ≥T1 was a low-*complexity* reading that conflated a
  small write with advisory-intelligence traffic; only the read-only `maintenance` class floors below T2
  (T0). No code change (`builtin.py` already had T2 — comments added to pin the rationale against future
  drift); the router (0.3.82) already inherited the code values, so writer behaviour is unchanged. This
  closes the "recorded, not fixed" note from 0.3.82. (The router's "Advisory only" scope is untouched —
  the verifier/reviewer stay frontier per the operator's decision; widening to route the verifier at T1
  remains a one-line table change available on request.)
- **2026-07-02 rev 0.3.82.** **Tier→model router — advisory traffic runs a cheaper model, the writer
  and the quality gate stay frontier (§S2 tiers realized; no invariant change).** The spec §S2 declared
  cost tiers T0–T3 and per-class `tier_minimum`, enforced only as a dispatch FLOOR (Inv 16); nothing
  ever mapped a tier to a concrete model — every LLM call ran the frontier `claude-fable-5` via
  `default_model()`. `models.py:model_for_tier(tier)` is the router the spec flagged as a follow-up:
  T2/T3 → `claude-fable-5` (frontier), T0/T1 → `claude-sonnet-5` (cheaper advisory), unknown → frontier
  (fail safe); `DEVHARNESS_MODEL` still pins the whole process. It lives in `models.py` — the only file
  the no-hardcoded-id guard exempts. **Scope = "Advisory only"** (operator decision): the pure-advisory
  exploration traffic routes to T1 — research interview + synthesis, the scope widener, discovery, and
  retro residue analysis (all threaded via the existing `model=` kwarg seam through `MCPClient`; the
  console + all three script drivers routed for parity). The **single writer stays frontier**
  (`default_model()` == `model_for_tier("T2")`, so no threading needed), and the **done-earned-twice
  quality gate stays frontier** — `live_parallax_client()` gained an optional `model=` so the verifier +
  fresh-context reviewer keep the default while research passes T1. An adversarial review confirmed no
  quality-gate or writer site was downgraded (the dangerous direction) and caught one missed advisory
  site (`run_developer.py`'s scope widener) — now routed. **Recorded, not fixed:** `builtin.py` sets
  `bugfix`/`dependency_bump` to `T2` while the §S2 table says ≥T1 — the router inherits the code values
  (those classes stay frontier); realigning the class floors is a separate decision. Second of the paired
  cost features (cost visibility, 0.3.81, is how the saving is seen). 1436 runtime green.
- **2026-07-02 rev 0.3.81.** **Cost is now visible — a console `$` view + a dashboard `cost` tile
  surface the spend that was recorded but hidden (§S9 tile 26→27; no invariant change).** `cost_spent`
  has fed `proj_cost` from every real spender since rev 0.3.60, but there was NO operator surface —
  `proj_cost` was even listed among the "feedless B0 placeholders." Two surfaces: **console `$`** opens
  a viewer (reusing the `_list_in_viewer`/`_ViewerModal` machinery) with per-role totals (from
  `proj_cost`), per-project totals (reconstructed from the raw `cost_spent` events' `correlation_id`,
  since `proj_cost` collapses to per-role), and a grand total; the `#state` panel also shows the grand
  total inline. **Dashboard `cost` tile** (`CostTile.svelte`, the dedicated-tile SSE pattern) accumulates
  per-role spend live from `cost_spent`. Both manifests updated for C7 parity (registry + §S9, 26→27);
  the boot check + `test_b5_tile_manifest`/`test_invariant_c7_b5` re-enforce at 27. No new event type
  (`cost_spent` already exists). First of the two paired cost features (the tier→model router follows).
  1433 runtime green.
- **2026-07-02 rev 0.3.80.** **The operator CLIs get the console's store-path hygiene — a typo'd
  `DEVHARNESS_DB` no longer silently signs into a phantom store (CLI robustness; no invariant
  change).** All eight `devharness` CLIs (`sign`/`answer`/`retro`/`prune`/`ratify`/`memory`/
  `questions`/`work_items`) opened their store with a raw `sqlite3.connect(DEVHARNESS_DB)` and no
  path resolution — the exact footgun rev 0.3.63 closed for the console, left open on the CLI side
  (flagged in HANDOFF as a carried watch-item). A relative/typo'd value against the wrong cwd either
  fails bare (sqlite names no path) or silently CREATES a fresh empty store that `migrate` makes look
  legitimate — so an operator `sign`/`answer` lands in a phantom store, the CLI sibling of the
  wrong-target contamination. New shared `cli/_bus.open_store()`: resolves a file-backed
  `DEVHARNESS_DB` to ABSOLUTE, fails closed on a missing parent naming the resolved path, and
  ANNOUNCES a created store on stderr (creation stays allowed — `memory import` may target a fresh
  store — but never silent). All eight CLIs now route through it. Four tests (fail-closed, announced
  creation, silent existing-open, relative→absolute). 1431 runtime green.
- **2026-07-02 rev 0.3.79.** **`role_transitioned` is now emitted — the dashboard's "Active role"
  tile is no longer dead (telemetry wiring; no invariant change).** Companion to rev 0.3.77: that fix
  made the CONSOLE's active-role line read its live `_busy` state, but `proj_role_state` — which
  feeds the dashboard's "Active role & FSM state" tile — stayed unwritten (nothing in the runtime
  emitted `role_transitioned`, a B0 projection stub). The console now emits `role_transitioned` at
  each build-step boundary (`_begin` → the step's role, `_end` → `idle`), tracking `from_role`
  across transitions. Telemetry-only and console-local: a failed emit never breaks the build step,
  the projection is a singleton so the correlation is provenance only, and it flows through
  `emit_sync` (no direct write). Driver runs (`run_*`) still don't emit it — the console is the
  primary surface; wiring the drivers is a follow-up if their dashboard view ever matters. The
  replay/parity invariant holds (the handler is deterministic). Test: `_begin`/`_end` emit
  `developer → idle` with correct `from_role`, and the projection reflects the latest. 1427 runtime
  green.
- **2026-07-02 rev 0.3.78.** **Research over-interviewing bounded — a diminishing-returns stop plus a
  tighter cap (research UX/efficiency; no invariant change).** Live this session, an a private build bugfix drew
  SIX near-adjacent scoping questions on a settled one-clause fix; each was a legitimate probe, but
  the growing elicit context tipped parallax's own inference into a `-32603` validation error (rev
  0.3.76 now degrades that gracefully, but the over-interviewing still wasted operator time + spend).
  Two bounds: **(1)** once `min_questions` (2) is met, the loop stops when the elicit payload
  self-reports `signal_level == "low"` — parallax's own signal that the remaining divergences aren't
  worth resolving (`_low_signal`; any parse failure / missing field keeps interviewing, so it only
  ever stops EARLIER, never later, and only on an explicit low signal). **(2)** the `max_questions`
  default drops 8 → 5 — the hard backstop when parallax never reports low. The operator still shapes
  scope at the sign-off gate, and the rev-0.3.68 confirmation turn still handles a well-specified
  seed in one turn. Two tests (low-signal stops at the minimum; high-signal caps at 5). 1426 runtime
  green.
- **2026-07-02 rev 0.3.77.** **"active role: (none)" during a running build — the panel read a dead
  projection; it now shows the live running step (console UX; no invariant change).** The operator
  saw `active role: (none)` while a developer dispatch was clearly running (`→ next: running:
  developer dispatch`, `tasks: running=1`) and read it as "not working." Root cause: `active_role`
  reads `proj_role_state`, populated ONLY by `role_transitioned` — and a grep confirms NOTHING in
  the runtime emits `role_transitioned` (a B0-era projection stub with no writer), so the field is
  `(none)` in every run. The console tracks step liveness through its own `_busy` flag (which is why
  the `→ next` line is correct), but the panel displayed the dead projection value. Fix: the
  active-role line derives from `_busy`, mapped to the role doing the work (research/director/
  developer/reviewer/integrate), else `(idle)`. Console-local, honest (it shows what's actually
  running). Recorded, not fixed here: `proj_role_state` remains unemitted, so the dashboard's
  role-state tile is likewise always `(none)` — wiring `role_transitioned` at the loop's role
  boundaries is a separate, dashboard-facing item. 1424 runtime green.
- **2026-07-02 rev 0.3.76.** **An errored `elicit` was surfaced to the operator AS an interview
  question — research now degrades on a parallax failure instead of showing the raw error (research
  resilience; no invariant change).** Live on the a private build bugfix (a 5-round interview): parallax's
  `elicit` failed server-side (`MCP error -32603 … preference arrays disagree: 6 texts, 5 signals`
  — its own inference produced misaligned arrays, correlated with the long interview's accumulated
  context). The interview loop read `question.output` without ever checking `question.is_error`
  (unlike the synthesis path, which does), so the raw MCP-error text flowed through
  `_strip_foreign_memory`/`_no_divergence` (neither matched) and was emitted as a `question_asked` —
  the operator saw the error as a question, and answering it just re-hit the erroring call. Fix: the
  loop checks `question.is_error` right after `elicit` and, on error, stops interviewing and
  synthesizes from the rounds gathered so far (the operator still shapes scope at the sign-off gate;
  `_synthesize_body` uses `complete()`, not the erroring `elicit` tool, and already degrades to the
  template on its own error). The `diverge` fallback got the same guard (its errored output no longer
  becomes a low-confidence assumption). Regression test: an errored elicit emits no `question_asked`,
  still drafts a spec, and the diverge placeholder is used instead of the error text. (Contributing
  observation, not fixed here: the research role asked five near-adjacent scoping questions on a
  one-clause fix; the growing elicit context is what tipped parallax's inference — interview-length
  tuning is a separate item.) 1423 runtime green.
- **2026-07-02 rev 0.3.75.** **The console can switch projects and start new ones without quitting —
  the store is no longer bound for the process lifetime (console UX; no invariant change).** Operator
  friction: to work on a different project the operator had to `q`, relaunch PowerShell with a
  different `DEVHARNESS_DB`, re-set the build target, and re-seed — because the console binds ONE
  store (connection + writer + follower + target all hung off it) at launch. Two new actions:
  **`P` — switch project**: discovers the sibling `*.db` stores beside the current one
  (read-ONLY per store — a raw `mode=ro` URI connection reading the latest `build_target_set`, never
  `ConsoleApp.connect` which migrates=writes, the review's catch), lists each as `store → target`,
  and reconnects to the chosen one (or a typed path) — closing the old connection and restoring the
  new store's target, on the UI thread. **`N` — new project**: one prompt (`name | repo | seed`)
  creates `var/<name>.db`, sets the target, and starts research in a single action (the new-empty-store
  warning re-announced on the swap). Guarded by the existing `_busy` flag — a switch is refused
  mid-build (the build worker reads `self._console.db_path` LIVE, so a swap under it would corrupt;
  the guard is load-bearing, documented). The state panel re-derives from the new store immediately;
  builds drive their own `_progress`/`_refresh`. **Honest limitation (documented):** the SSE sidecar
  tails a FIXED store, so with one running the progress pane keeps showing the launch store's events
  until the sidecar restarts — the switch is clean on the no-sidecar poll path (the solo-operator
  norm); a note is logged when a follower may be live. Three tests (reconnect + target restore, the
  mid-build refusal, the new-project create+target+research chain). 1422 runtime green.
- **2026-07-02 rev 0.3.74.** **A pending mid-research question was hidden behind "running: research"
  — the state panel now surfaces it while busy (console UX; no invariant change).** Live during the
  a private build bugfix's interview: the research role asked a question, but the `→ next` line only said
  `running: research (ctrl+x to cancel)` and never named the pending question, so the operator
  thought it was stuck ("it's not doing anything"). Root cause: `_next_hint` returned the busy line
  at the top, before the pending-question branch — and during research `_busy=="research"` for the
  whole run (the worker thread polls silently for the answer), so the question hint was unreachable.
  Fix (`_next_hint` only): while busy with `research`, a pending question surfaces as
  `A — answer (research is waiting): <question>`; gated to `research` (the sole step that asks
  questions), so a director/developer/oss step keeps the plain running line. The panel already
  re-renders on the ≤2s poll tick + every SSE frame (`question_asked` ∈ `_PROGRESS_EVENTS`), so no
  cadence change was needed; it inherits the existing in-flight-run question scoping (rev 0.3.69), so
  no stale-question hijack. Also surfaces the rev-0.3.68 confirmation turn while busy. Regression test
  covers the surfaced question, the non-research busy line unchanged, and the no-pending-question
  fallthrough. 1419 runtime green.
- **2026-07-02 rev 0.3.73.** **The first console-driven `bugfix` crashed the verifier and would have
  silently false-certified — class fields now derive from the realized diff, the verifier fails
  closed, and the baseline overlays the new regression test (§S2 class verifiers; no invariant
  change).** Live on a a private build XSS bugfix (`"` in a link href breaks the double-quoted attribute):
  the director classed the task `bugfix`/`bugfix_regression` correctly but left `regression_test_ref`
  empty — only the operator-injected SCRIPT flow ever set it — and the verifier did
  `context["regression_command"]` → **KeyError**, dispatch died with NO terminal, `W` re-crashed
  (the rev-0.3.70 `dependency_bump` WinError-87 shape exactly). The adversarial review caught that
  fixing only the crash would be WORSE than the crash: a `bugfix`'s regression test is NEW in this
  task, so the `--include-untracked` baseline stash removes it — at baseline `pytest <newtest>` exits
  "file not found", which the `baseline_should_fail` axis misreads as "bug demonstrated" → a silent
  false-certification. Fixes: **(1)** `bugfix_regression` fails closed with a named reason on a
  missing command (restores the reject-terminal flow so `W` stops looping). **(2)**
  `class_commands.derive_regression_test_ref` derives the ref from the realized diff — exactly one
  test file (pytest naming or a `tests/` path) or "" (fail closed); no LLM text reaches a subprocess
  (C0). Wired at all four vctx sites (console developer, run_developer, run_oss, console OSS), explicit
  task refs winning. **(3)** a bugfix-only baseline **overlay** (`_baseline.at_baseline(overlay=…)`,
  refactor passes None so its path is byte-identical): the verifier reads the new/modified test's POST
  content before the stash and writes it onto the baseline (fix absent) so the test genuinely fails —
  the axis is real, not vacuous, and a "regression test" that passes against unfixed code is correctly
  REJECTED. Surfaced during that fix, in the shared baseline: the baseline suite run regenerates
  `__pycache__/*.pyc` that collide with the stash's untracked caches → `stash pop` aborts ("already
  exists, no checkout"); `at_baseline` now purges caches before the pop (the rev-0.3.58 hazard at a
  new git surface; latent for refactor too). 11 tests incl. a console end-to-end bugfix reaching
  `completed` on a derived ref against an overlaid baseline, and the not-vacuous / correctly-rejected
  baseline cases. 1418 runtime green.
- **2026-07-02 rev 0.3.72.** **The list actions (c/p/g) get the spec viewer's treatment — a list
  renders in the dismissable scrollable modal, not the append-only log (console UX; no invariant
  change).** Live on the first real candidate review: `c` dumped the pending-candidate JSON into
  the log pane — the exact defect `v` had already fixed for spec bodies (rev 0.3.55: content
  scrolls the log away with no keyboard way back). All three list actions (`c` candidates, `p`
  expired grants, `g` approved gate-changes — the same rendering surface) now route through a
  shared `_list_in_viewer` → `_ViewerModal` (which is already markup-safe per 0.3.62); an EMPTY
  list stays a one-line log entry (no modal for nothing), and the log line notes Escape closes.
  Flow note: app keys are inert while the modal is open, so the review flow is c → read → Escape →
  `a`/`j` — the same shape as v → Escape → s.
- **2026-07-02 rev 0.3.71.** **The console gets the dispatch-time scope widener (run_developer
  parity) — and the widener's result now reaches the worker's PROMPT, not just enforcement (§S4
  scope; no invariant change).** Live continuation of the 0.3.70 a private build bump: with the crash
  fixed, the retry rejected on a REAL failure — the repo's own `test_packaging_pinned_version`
  asserts the old version, the director scoped the task to dependency metadata only, and §S4 means
  the worker PHYSICALLY cannot edit the out-of-scope pin test — the task was structurally
  uncompletable, every retry doomed. This is exactly what `resolve_extra_scope` exists for, and the
  console never wired it (a parity gap the rev-0.3.60 review had flagged; the widener predates the
  console). Port: `ConsoleDeveloper._make_scope_widener` — external non-OSS targets, guarded by the
  developer_kwargs-is-None gate (stubbed-kwargs tests never spawn an SDK session), cost emitted
  task-scoped (`role=scope_resolver`, SC-6). The adversarial review then caught that the port alone
  would NOT fix the live case: the widener's union governed both enforcement layers but
  `_worker_prompt` still rendered the bare plan globs — the worker OBEYED the narrow prompt and
  never touched the widened files (the widener only stopped enforcement from rejecting edits the
  worker was told not to make) — a latent bug in the script driver too. `_worker_prompt` now
  renders the effective union and names the widened files explicitly ("an existing test
  contradicting the change is part of the change"), overriding a narrower task description. Note
  the 0.3.70 rejection itself was CORRECT behavior — a readable, non-crashing refusal of an
  incomplete change; this rev makes the complete change plannable.
- **2026-07-02 rev 0.3.70.** **The first console-driven `dependency_bump` crashed the dispatch —
  class fields now derive deterministically from the realized diff, and the verifier fails closed
  (§S2 class verifiers; no invariant change).** Live on the a private build drive: the director's
  decomposition classed the task correctly but left ALL five class fields empty
  (`dependency_name`/`target_version`/`bump_command`/`manifest_path`/`lockfile_path`) — only the
  operator-injected script flow (jqlite) ever populated them — and `dependency_resolves` then
  crashed the dispatch (`subprocess` of the empty bump_command → `OSError WinError 87`) with NO
  terminal emitted, so `W` re-selected the task and crashed identically forever. Two latent bugs
  under it: empty name/version would VACUOUSLY PASS axes 2–3 (`'' in content` is always true), and
  an empty `lockfile_path` made `_read` open the worktree DIRECTORY — plus a no-lockfile project
  (a private build: requirements-only) could never satisfy axis 3 at all. Fixes, adversarially reviewed
  before implementing (the review corrected the design twice): **(1)**
  `class_commands.derive_bump_fields` — the fields derive from the REALIZED DIFF (C0
  verify-what-happened; no LLM-authored text ever reaches a subprocess — F4): the changed manifest
  (requirements*.txt / pyproject.toml allowlist; the review dropped setup.cfg/Pipfile as
  parser-less), added-line `name[extras]? ==|>=|~=|=== version` parse (extras + ranges are
  legitimate bump shapes — jqlite's was `rich[color]==13.9.4`; comments/markers stripped), exactly
  ONE distinct (name, version) pair or the fields stay empty (a first-match guess could verify the
  wrong dependency), and a fixed per-manifest-kind `pip install --dry-run` bump command.
  `lockfile_path` derives from the WORKTREE, not the diff — the review's gate-weakening catch: a
  project whose lockfile exists but was not regenerated must FACE the axis, not skip it. All four
  drivers (console developer, run_developer, run_oss, console OSS) fill ONLY empty vctx fields, so
  an operator-injected task's explicit fields always win. **(2)** the verifier fails closed with a
  named reason on missing fields (restoring the normal rejected-terminal flow — the crash emitted
  none) and SKIPS the lockfile axis with recorded evidence only when the project has no lockfile.
  11 new tests incl. a console end-to-end bump reaching `completed` on derived fields. The stuck
  a private build t0 re-dispatches cleanly (fresh lifecycle per dispatch; the crash left no lock).
- **2026-07-02 rev 0.3.69.** **A second research correlation's interview was invisible to A — the
  answer lookup now scopes to the in-flight research run (console UX; no invariant change).** Live
  on the a private build `dependency_bump` drive, first exercise of the 0.3.68 confirmation turn: the
  question was asked and research blocked polling for the answer, but `A` said "no unanswered
  question". Root cause: `_latest_unanswered_question`/`_pending_question_text` scoped to
  `_latest_correlation()`, which PREFERS the signed spec's correlation (right for D/W, wrong for
  questions) — in a store whose first build already signed a spec, a NEW research correlation's
  pending question can never be found. Never bitten before because every prior console research ran
  in a fresh store, and after `328e2ab` the interview asked zero questions — 0.3.68 restored
  questions and exposed this within the hour (the layered-defect pattern again). Fix:
  `_question_correlation()` — scope to the latest `research_started` correlation while that run has
  no drafted spec yet (in flight), else fall back to the signed-spec correlation, preserving the
  original orphan-hijack protection (an abandoned run's question stops owning the hint at the next
  drafted spec). `submit_answer` was already correct (inherits the question's own correlation).
  Two regression tests (the exact live scenario; the orphan fallback). The blocked drive itself is
  unrecoverable in-place — the running console holds the old code and a side-channel
  `question_answered` emit would race the hash chain (a second writer connection) — so the recovery
  is cancel + relaunch + re-run R (one research spend).
- **2026-07-02 rev 0.3.68.** **Research always gives the operator a confirmation turn — the interview
  no longer silently vanishes on a well-specified seed (research UX; no invariant change).** Reported
  live: "I never get interviewed anymore." Root cause: commit 328e2ab (rev 0.3.37) made research
  interview ONLY when parallax `elicit` reports non-empty `divergence_points`; a complete seed makes
  elicit return `divergence_points: []` (verified live on the a private build seed), so the loop recorded the
  assumed objective as a 0.7 assumption and broke with ZERO `question_asked` events — the operator's
  pre-spec scope-shaping seat disappeared for every recent build (a private build/a private build/a private build: 0 questions;
  dedup/r1 before 328e2ab: 3–12). Parallax `decide` (90 vs 62/48/25): on no-divergence, present
  exactly ONE confirmation turn — the assumed objective + the STATED `governing_preferences` (the
  silent assumptions elicit surfaced) rendered as a plain-text question, "I will build X assuming
  A/B/C — reply 'ok' or correct." A bare ack (`ok`/`yes`/`lgtm`/…) records only the objective; any
  other answer is captured as an `operator scope note` assumption threaded into synthesis. This
  restores the seat WITHOUT the fixed-N re-distillation 328e2ab deliberately removed (exactly one
  turn, then synthesize). Revealed/inferred preferences are excluded (revealed can be cross-project
  memory, already stripped by rev 0.3.48's `_strip_foreign_memory`; inferred is a guess). The old
  `test_no_question_when_objective_is_unambiguous` (which asserted the zero-question behavior) is
  replaced by two tests: the single confirmation turn + the correction-becomes-a-scope-note path.
  1394 runtime green.
- **2026-07-02 rev 0.3.67.** **F4 partially closed — the channel-independent untrusted-text→LLM
  surfaces in the §S5 OSS envelope are covered, reusing the rev-0.3.44 primitives (OSS injection
  hardening; no invariant change).** A full trace found the rev-0.3.44 context-separation defense
  lived ONLY in the parallax verifier/guard paths; three untrusted-external-text surfaces reached an
  LLM with no defense, all true regardless of the (still undefined) intake channel. Parallax `decide`
  (88 vs 22/58/30): close the channel-independent gaps with existing primitives, don't build a
  speculative firewall (the F1 trap) and don't defer real gaps. **(1)** `injection_scan.scan_repo_files`
  scans the upstream clone's README/CONTRIBUTING/AGENTS.md/CLAUDE.md/.github-instructions (the fork
  worktree is the untrusted checkout; the worker's built-in reads stay live) — wired into
  `process_intake(repo_path=…)`, both drivers pass the local upstream path; the module docstring's
  false "scanned in later sub-phases" claim (an actual correctness defect) is gone. **(2)**
  `DeveloperRole._oss_injection_refusal` marker-scans the OSS description + spec_claim BEFORE the SDK
  worker runs — a hit sets `gate_denial`, the director rejects (no worker invocation, no commit),
  reusing the marker scan + the gate-denial→rejected-terminal plumbing (the largest surface: an OSS
  instruction goes RAW into the worker prompt, which has no context-separation seam). **(3)**
  `parallax_check` + `parallax_grounded_verify` (claim-only) now marker-scan the claim and fail SAFE,
  the sibling of `parallax_verify` — closing the reviewer default-verifier path where an untrusted
  description could self-certify with a `Verdict: supported` payload. **Residual (channel-dependent,
  still gating with F1):** the phrase denylists are evadable by rewording/homoglyph/non-English —
  hardening evasion-resistance depends on the intake channel + source trust, deferred as speculative;
  the structural exposure is closed, the denylist strength is not (`claudedocs/oss-trust-model-prerequisites.md`).
  Operator confirmed external contributions are an eventual goal, so F1/F4 are live roadmap items.
  7 tests; 1393 runtime green.
- **2026-07-02 rev 0.3.66.** **Spec OQ1 + OQ3 resolved — the last open questions close; the first
  evidence-based cap ratification lands (#M4).** **OQ1:** every gate is born-enforcing, settled by
  practice and recorded: all 13 landed gates chose enforcing under the B2 per-gate rule, no
  observe/log-only machinery exists in `gates/` (grep-verified), and observe-mode is now NOT a
  supported state — a future gate wanting one amends the spec first. **OQ3, three axes:** tier
  minimums ratified as-is (code floors at-or-above every §S2 floor; bugfix/dependency_bump enforce
  T2 against the table's ≥T1 — stricter is compliant); the `feature` blast-radius cap is TIGHTENED
  30→21 from realized telemetry (60 tasks / 7 projects, observed_max 14, `ratify.py`'s own
  ceil(max × 1.5) — the deliberate operator act the M4 register item awaited, operator-authorized
  2026-07-02); reasoning budgets ratified as conservative defaults per the B2.8 precedent with the
  telemetry gap named (director token spend enforced in-memory, never persisted — the rev-0.3.60
  USD telemetry accrues the future basis). Remaining classes' caps stay conservative until
  `emit_cap_recommendations` crosses their 20-sample thresholds organically. Also recorded:
  the operator confirmed (2026-07-02) that real external OSS contributions are an EVENTUAL goal —
  F1 (maintainer authentication) + F4 (injection resistance) are genuinely gating roadmap items,
  not parked speculation. With OQ1–OQ5 all resolved, the spec's §Open Questions block is closed.
  1386 runtime green (one cap assertion updated to the ratified value).
- **2026-07-02 rev 0.3.65.** **Spec OQ4 resolved — trusted-memory staleness policy deliberately
  deferred until a production consumer exists, with a STRUCTURAL reopen trigger (spec resolution +
  one guard test; no mechanism built).** The deciding fact (grep-verified): trusted memory has zero
  production consumers — only `boot.py`'s Inv-17 parity check calls `list_verified_memory`; the
  antibody library bridges INTO memory but no decision path reads OUT of it — so staleness has no
  point-of-use impact and a downgrade mechanism would be unexercised machinery (YAGNI). Parallax
  `decide` (78 vs 62/45/24): defer-with-trigger beat building the prune-pattern mirror now, the
  auto-sweep, and silent point-of-use decay (the latter two rejected on the operator-in-the-loop
  trust model + the silent-behavior defect class). The full OQ4 entry records the pre-decided
  direction so the reopen never re-litigates: advisory TTL report, operator-authorized
  `memory_entry_downgraded`, re-verify via the existing Inv-17 path. The reopen trigger is a guard
  test (`test_oq4_reopen_trigger_no_production_consumer_of_trusted_memory`): the first runtime file
  beyond the definition + boot check to reference `list_verified_memory` fails CI with a message
  naming OQ4 and the recorded direction. 1386 runtime green.
- **2026-07-01 rev 0.3.64.** **Director over-decomposition fixed at the source — the decompose
  prompt folds inherent error/edge cases into the task that introduces the code (planning
  efficiency; no invariant or gate change).** The §Post-B5 redundant-task pattern (csvlite t2/t5):
  the #2b prompt's per-behaviour split rule ("one task per independently-verifiable behaviour, do
  not bundle") had no carve-out for an error/edge criterion whose behaviour another task's
  implementation NECESSARILY produces (the validation error a parser already raises on malformed
  input), so such criteria were planned as standalone tasks that reached the developer as empty
  test-only diffs the spec_claim axis correctly rejects — a wasted multi-minute worker run per
  occurrence, absorbed but not prevented by the rev-0.3.37 advance-past-terminals behavior.
  Parallax-decided design (82 vs 52/45, weigh): **prompt-only** — the deterministic post-parse
  merge lost as keyword-shaped (the heuristic form this project has refuted repeatedly, and it
  risks over-merging real work), the LLM post-check lost on layering a worker-run-scale cost + its
  own hardening burden onto a failure the verifier already absorbs. The prompt now carries BOTH
  directions: the split rule stays (the jqlite under-decomposition fix), plus the EXCEPTION —
  inherent error/edge behaviours fold into the introducing task's description/verification, and a
  separate error-handling task is planned ONLY when it needs its own new code (a private build t1's
  exception→exit-code mapping was real code; the fold must not swallow that class back into
  under-decomposition). Structural regression test asserts both rules + the carve-out coexist in
  the prompt; behavioral validation is organic — the next console-driven director plan exercises
  it live. 1385 runtime green.
- **2026-07-01 rev 0.3.63.** **Event-store path hygiene — a bad `DEVHARNESS_DB` fails closed with
  the resolved path named; a brand-new store is announced, never silent (console UX; no invariant
  change).** Live on the a private build resume: the operator launched the console from `runtime\` with the
  relative `var\a private build.db` — sqlite raised a bare `unable to open database file` naming NO path
  (the missing-parent case), and had the parent existed, sqlite would have silently CREATED a fresh
  empty store at the wrong location, which `migrate` then dresses up as legitimate — the operator
  burns research spend against the wrong store before noticing (the store-side sibling of the
  rev-0.3.61 wrong-target contamination; same class as the a private build incident, one layer down).
  Parallax-decided design (82 vs 68 for fail-closed-always; the 0.3.61 warning-only precedent and
  the documented one-keypress new-project flow were deciding): `ConsoleApp.connect` resolves a
  file-backed path to ABSOLUTE before opening (worker threads and mid-session cwd changes can
  never re-resolve it differently); a missing parent directory fails closed with a
  `FileNotFoundError` naming the resolved path (the TUI `run()` and `status` entrypoints render it
  as one clear stderr line, exit 1 — not a traceback); a missing FILE under an existing parent is
  still created (the new-project flow) but `store_created` is announced loudly in the TUI log and
  the `status` stderr — "created NEW EMPTY event store at <abs path>". `:memory:` untouched. Six
  regression tests (missing-parent fail-closed naming the path + nothing created, relative→absolute
  + created-flag, existing-store not flagged, `:memory:` hygiene-exempt, on_mount announces a new
  store, on_mount silent on an existing one). The sibling CLIs (`cli/sign.py`, `cli/retro.py`, …)
  share the raw `sqlite3.connect(env)` pattern and are deliberately out of this bounded fix's
  scope. 1384 runtime green.
- **2026-07-01 rev 0.3.62.** **Store text rendered as Textual markup crashed the console — every
  widget sink of store/LLM-derived text now renders literally (console UX; no invariant change).**
  Live on the a private build drive: pressing `v` on a spec whose JSON body contained
  `["packaging==24.0."]` killed the WHOLE app with a `MarkupError` — square brackets in
  store-derived text parse as Textual markup tags, and the parse happens at compositor reflow
  (layout time), outside any action handler, so the console's per-action error logging structurally
  cannot catch this class. Three sinks had markup enabled (the two RichLogs were already
  `markup=False` — the class was half-closed once): the `_ViewerModal` body (`Static`), the
  `#state` panel (whose `.update()` embeds `_next_hint()`'s terminal reasons and the pending
  research question), and the `_InputModal` prompt `Label` (the A-prompt renders the LLM question
  verbatim). All three now pass `markup=False` — which the adversarial review verified covers both
  the constructor and every later `.update()` in the installed Textual 7.5.0. The review caught a
  FOURTH sink the fix as designed missed: `border_title` parses markup UNCONDITIONALLY (ignores the
  widget's flag), and the viewer's title embeds the store-derived spec id — fixed by passing a
  pre-built `Content`, which the setter passes through unparsed. Bonus live display bug cured by
  the same fix: the W prompt's literal `[task_id]` hint was being EATEN by markup — operators saw
  `correlation_id ` — since the prompt shipped. Four regression tests (the exact crashing body, a
  bracketed title, a bracketed prompt, a bracketed terminal reason through the state panel — the
  reflow-survival IS the assertion). 1378 runtime green.
- **2026-07-01 rev 0.3.61.** **Wrong-target contamination guard — the console warns when a build
  target carries scratch branches from correlations this store has never seen (console UX; no
  invariant or dispatch-behavior change).** The a private build incident: a stale re-entered build target
  landed an entire build in ANOTHER project's repo (a private build), discovered only at assemble time.
  The signal (`worktree/contamination.py`): scratch branches are `devharness/{task_id}` with task
  ids `{cid}-t{n}` (sole assignment site `roles/director.py`; re-drives reuse the id), and console
  stores are per-project — so every correlation that ever built into a repo THROUGH THIS STORE is in
  its event log, and a branch whose embedded correlation the store has never seen means another
  project's store built here. Same-store successive builds into one repo (the legitimate a private build
  feature-then-refactor pattern) stay silent, and the signal is path-independent (correlation sets
  survived the C:→D: migration where any target-path-history alternative would false-fire).
  **Warning-only, never a block** — re-targeting an old repo into a fresh store is legitimate; the
  operator confirms. Fires at T-set, at launch-restore, and (adversarial-review catch) on the
  env-only path — `DEVHARNESS_TARGET_REPO` with nothing restored never transits T/restore, so the
  restore hook checks the env target too; `run_developer.py` prints the same warning after boot.
  Out of scope by design: `devharness-oss/*` fork branches (a configurable prefix landing in
  upstream clones, a different entry surface) and `DEVHARNESS_SCRATCH_BRANCH` overrides. Review also
  confirmed the greedy `-t\d+$` parse recovers a correlation that itself ends in `-tN`, and that no
  legitimate steady-state workflow repeat-fires (the only persistent warner is a recreated store for
  a repo with old scratch branches — a genuinely cross-store situation that deserves it).
- **2026-07-01 rev 0.3.60.** **SC-6 completed — every real LLM spender now emits `cost_spent`, and
  the criterion is reworded to the contract the system actually enforces (§S9 cost telemetry; no
  invariant change).** An inventory + adversarial review against source found five spenders whose
  realized cost was still silently discarded after 0.3.56: **(1)** the dispatch-time scope widener —
  `resolve_extra_scope` read `total_cost_usd` only as a result-message sentinel and dropped the value;
  now takes an optional `cost_sink(amount_usd)` (the role stays SDK-only — no bus inside; the
  `run_developer` closure owns the emission, `role="scope_resolver"`, task-scoped). **(2)** the retro
  residue analyzer — `run_maintenance` constructed its `ParallaxClient` INLINE into `make_llm_fn`, so
  the accumulated spend was unreachable; the client is now bound and one `role="retro_residue"`
  emission lands after `drive()` (deliberately role-scoped: retro analyzes PAST tasks' terminals, and
  per-terminal attribution would thread cost deltas through the engine for advisory overhead).
  **(3)** `run_oss`'s loop-owned parallax client (in-lock verifier + fresh reviewer + non-goals) —
  loop-end `verify_review` emission, task-scoped only when exactly ONE OSS task ran (one client
  serves the whole list; a multi-task total pinned to one `task_id` would fabricate attribution).
  **(4)** the console OSS action — it dispatches via `DirectorRole.run`, never through
  `ConsoleDeveloper.dispatch`, so the 0.3.56 `verify_review` emission never fired on the OSS path;
  same loop-end emission added. **(5)** `run_promote`'s parallax client (the review's catch — missed
  by the design), `role="promote"`, role-scoped (a spec draft has no task yet). With all five, "every
  real spender emits" actually holds, which is what licenses the wording amendment: SC-6's original
  `cost.tick` phrasing predated the implemented event (`cost.tick` appears nowhere in code and matches
  no registry convention — all 58 event types are snake_case), its flat-cost half is vacuous
  (maintenance never emits task terminals), and its "no task terminates with cost absent" absolute is
  unassertable in an all-mocked suite where zero-spend runs deliberately emit nothing. Nothing binds
  the old wording (no boot check, test, or constitution claim references SC-6 — verified), so the
  criterion now states the enforced contract: every real spend recorded, task-scoped wherever
  attribution is real, zero-spend silent. Tests: the `cost_sink` fires-iff-spent unit + the console
  OSS emission (and zero-cost silence) regression.
- **2026-07-01 rev 0.3.59.** **The 0.3.58 cache fix failed its first live retry within the hour —
  TRACKED caches are a second layer the rm-tree purge made worse, fixed by normalizing cache state to
  exactly-HEAD (§S4 scope enforcement; hygiene v2; no invariant change).** The retried refactor was
  rejected AGAIN with the same scope_violation: the target repo had 12 `.pyc` files already TRACKED —
  committed by the harness's own pre-0.3.58 scratch commits — and tracked caches defeat both 0.3.58
  defenses (`.gitignore` never affects tracked files; the v1 purge DELETING them registered `D` entries,
  making the fix itself the violation). The first rejection had been tracked-cache `M` entries all
  along (test runs regenerate tracked caches), compounded by the untracked ones. **Hygiene v2:**
  `purge_bytecode_caches` now (1) rm-trees cache dirs as before (symlink-guarded), then (2) restores
  any TRACKED cache paths to HEAD content — `git ls-files -z` (NUL-split, immune to `core.quotepath`)
  filtered on cache segments, batched `git checkout HEAD -- :(literal)<path>` (the adversarial review
  caught that plain `checkout --` restores from the INDEX, so a worker that STAGED a poisoned tracked
  `.pyc` would get it faithfully re-materialized; `HEAD --` reverts it — and `:(literal)` guards
  against a hostile upstream filename acting as a wildcard pathspec). Net contract: after the purge,
  cache dirs hold exactly the tracked-at-HEAD files — zero porcelain noise, nothing cache-related
  stageable, hand-written payload in tracked caches reverted. This also closes the v1 OSS residue the
  review confirmed: `commit_with_identity`'s `add -A` runs after the purge with no scope re-check, so
  v1's deletions of tracked caches would have shipped silently in a PR branch. The operator's repo was
  cleaned (`git rm -r --cached`, 12 files); non-git roots keep v1's rm-tree-only behavior (the git
  steps no-op), so the unit-test contract is unchanged. 1366 runtime green.
- **2026-07-01 rev 0.3.58.** **The first console-driven refactor was rejected over compiler exhaust —
  bytecode caches are now purged at every harness git surface, T-created repos get a seeded
  `.gitignore`, and the blocked-hint truncates its reason (§S4 scope enforcement + console UX; no
  invariant change; also retroactively explains a private build's committed `.pyc` files).** The operator drove
  the first-ever non-feature class through the console: a behavior-preserving refactor of a private build. The
  worker did exactly the right thing — kept a temp copy of the old module, diffed outputs for
  byte-identity, ran the full suite in its worktree — and was REJECTED as a `scope_violation` listing
  only `__pycache__/*.pyc` paths: Python bytecode caches generated by running the tests, in a target
  repo that had no `.gitignore` (T git-inits repos bare, and no spec ever asked for one).
  `_worktree_changed_paths`'s docstring claimed gitignore-respecting exclusion of build artifacts —
  true only when the target HAS a gitignore. The same root cause had already shipped committed `.pyc`
  files into a private build's repo via the scratch-branch commit's `git add -A`. **Fixes:** (A) a shared
  `worktree/hygiene.purge_bytecode_caches` deletes `__pycache__`/`.pytest_cache` TREES at every harness
  git surface — in `DeveloperRole.run()` BEFORE the scope check (the adversarial review caught that the
  originally-proposed `_realized_diff`-only site would NOT have fixed the live defect: the scope check
  runs first and reads `git status` independently), at `_realized_diff` (the verifier's own pytest run
  regenerates caches), at both `_commit_scratch_branch` copies, at the OSS `commit_with_identity` (a
  gitignore-less upstream would have gotten caches in the PR branch), and at the `stage_and_commit`
  habit script (a mid-task worker commit would make caches TRACKED, defeating untracked-purges).
  DELETION deliberately, not diff-exclusion — excluding `*.pyc` from scope checks would let a
  shell-writing worker smuggle payload in a `.pyc`-named file; a bare `.pyc` outside a cache dir stays
  on disk and is scope-checked normally, and symlinked cache dirs are skipped, never followed (a worker
  could point `__pycache__` at in-scope files to get them deleted pre-check). (B) `_prepare_target`
  seeds a cache-covering `.gitignore` — only in repos it CREATES; existing repos keep their own
  conventions. (C) the blocked-hint truncates the rejection reason to 120 chars (a 9-file
  scope_violation produced a 9-line wall that drowned the retry command — the full reason stays in the
  event log). The checkpoint baseline was audited and excluded: it runs pre-worker in a fresh worktree,
  no caches can exist. 1365 runtime green.
- **2026-07-01 rev 0.3.57.** **The first REAL learning-spine run surfaced two defects — an env-posture
  gap that crashed it, and a burn bug that silently consumed every terminal in the store (§S7 retro +
  driver posture; no invariant change).** The operator ran `run_maintenance` on real build outcomes for
  the first time. **(1) API-key posture:** a stray `ANTHROPIC_API_KEY` in the environment kills the SDK
  subprocess at launch (exit 1) — the console pops it deliberately (rev 0.3.47 era) but none of the
  script drivers did, so the first script-driven LLM path ever run crashed immediately. All SEVEN
  `run_*` drivers now pop it at `main()` entry (the reviewed alternative — excluding it at the SDK
  boundary — is impossible: the SDK's child-env merge has no removal mechanism, and the CLI treats an
  empty-string key inconsistently across resolution paths); the `env -u` workaround is gone from every
  docstring, HANDOFF, and README. **(2) The burn:** `make_llm_fn` swallowed ALL failures to `[]`
  ("best-effort"), so while the SDK was down every residue analysis "completed" with zero candidates,
  the scheduler emitted `retro_run` per terminal, and the (task, kind) dedup permanently consumed all 8
  of the store's terminals as "analyzed, nothing found" — the analysis never actually happened.
  Transport-down and model-quality failures are different classes: a malformed reply from a successful
  call still yields `[]` (best-effort preserved), but a transport failure or errored result now raises
  `LLMUnavailable`, which propagates cleanly (the engine's LLM stage runs only when zero T0 candidates
  were emitted — no partial state) to the drive loop, which halts the retro drain and leaves every
  remaining terminal queued for the next window. The adversarial review traced the OBSERVED failure
  shape through the SDK source (a message-reader crash surfaces as a plain untyped `Exception` — the
  broad catch is deliberate) and confirmed exactly one test pinned the old swallow behavior. **Named
  residuals:** the 8 burned a private build terminals stay burned (no event-sourced re-open path exists; a
  `retro_run_invalidated` event would work but isn't worth it for 8 low-value rows — the valuable
  a private build/a private build outcomes were in OTHER stores, untouched); a pre-existing `asyncio.run`-in-running-
  loop issue (tech-debt R5) now surfaces as `LLMUnavailable` (mislabeled but strictly better than a
  silent `[]`); the drive halt also defers T0-only terminals to the next window (harmless). Also this
  session's environment finding, for the record: the documented `core.fsmonitor=false` global git
  config had silently regressed to `true` (likely a Git for Windows update), accumulating 1,894
  orphaned fsmonitor daemons — re-applied; the harness's own `resource_snapshot` warning correctly
  flagged it at launch. 1363 runtime green.
- **2026-07-01 rev 0.3.56.** **Cost telemetry exists now: `cost_spent` events feed the proj_cost
  projection, orphaned since B0 (§S9 "per-role spend" realized; SC-6 partially realized; +1 event type,
  EVENT_TYPES 57→58).** The operator asked what the a private build validation build cost — and the answer was
  unknowable: `proj_cost` ("tile 7: per-role cost vs budget") had ZERO rows in every store ever produced.
  No projection handler wrote it, no event carried cost, and the tile meant to read it was removed at
  rev 0.3.31 as a feedless placeholder. Real spend accumulated only in role memory (`MCPClient`/
  `DeveloperRole`/`DiscoveryRole` `total_cost_usd`; the scope-widener's cost is DISCARDED outright) and
  inside verifier evidence blobs — consumed live by the OSS usd cap, never recorded as telemetry, in
  direct violation of "the event log is the telemetry" and the §S9 cost requirement. **Fix:** a
  `cost_spent` event ({role, amount_usd, task_id?, spent_at_millis}) emitted where spend is known —
  `DeveloperRole.run()`'s finally (the worker session, task-scoped, covering denial early-returns),
  `ResearchRole.run()`/`DirectorRole.run()`/`DiscoveryRole.run()` ends (their clients' totals), and the
  dispatch-loop end in BOTH the console and `run_developer` (the loop-owned parallax client:
  verifier axes + fresh-context reviewer + non-goals check across all retry attempts, as
  `role="verify_review"` — one total per dispatched task, since that client persists across attempts).
  The adversarial review resolved the crux: the developer's worker session and the dispatch loop's
  parallax client are disjoint SDK sessions — no double-counting; and emission must NOT live in
  `director.dispatch` (an invariant test drives a fake developer with `total_cost_usd=999` through it).
  Handler: per-role cumulative upsert into proj_cost; `budget_usd` stays NULL (per-role budgets retired
  at constitution v0.2.0); replay-parity holds (pure event accumulation). Zero-cost (mocked) runs emit
  nothing, so the whole existing suite stays event-clean. **Named residuals:** SC-6's full contract
  (per-task cost on EVERY per-token task + zero-USD `cost.tick` for flat-cost tasks) remains open — this
  realizes the per-role aggregate half; the scope-widener's discarded cost; `run_oss`/`run_maintenance`
  driver-loop emissions; restoring a cost tile (§S9 manifest + C7 sync). 1360 runtime green.
- **2026-07-01 rev 0.3.55.** **Spec review (`v`) opens a dismissable scrollable viewer instead of dumping
  the document into the action log (console UX; no invariant change; live-reported mid-build).** The `v`
  action printed the entire spec JSON into the append-only `#log` RichLog — prior action results
  scrolled away, the log anchored to the tail, and the operator had no keyboard way to scroll back or
  dismiss the dump ("leaves me no way to return to viewing the log"). A document was being rendered
  into a log surface. New `_ViewerModal`: a read-only scrollable modal (arrows/PgUp/PgDn scroll, Escape
  closes), used by `v`; the log gets a one-line "reviewing spec <id>" entry instead of the body. The
  design's one genuinely risky assumption — whether app-level single-letter bindings (`q` quit, `W`
  dispatch...) still fire while the modal is open — was adversarially checked against the installed
  Textual source before implementing: the binding chain truncates at a modal screen, so they're inert
  (same mechanism that already protects `_InputModal`); focus/scroll/dismiss were live-probed through
  the real event pump first, per the 0.3.54 lesson. **Follow-ups flagged, not built:** three other
  actions still `_fmt`-dump potentially long payloads into the log (`c` candidates, `p` expired grants,
  `g` gate-changes) — viewer candidates when they bite. 1357 runtime green.
- **2026-07-01 rev 0.3.54.** **The rev-0.3.52 paste fix itself doubled every paste — caught on the very
  next live build, root-caused to Textual's MRO handler dispatch, fixed rewrite-only (console UX; no
  invariant change).** The `_JoinPasteInput` subclass shipped at 0.3.52 defined its own `_on_paste` that
  inserted the joined text — but Textual dispatches `_on_paste` for EVERY class in the MRO (its
  no-super() handler design), so the subclass handler did not replace `Input`'s: both ran, and every
  paste was inserted twice (a single-line paste doubled; a multi-line paste got joined-then-first-line-
  again). The live consequence on the a private build validation build: the operator's T value persisted a
  garbage doubled test command, and the R seed reached research doubled (the elicit/synthesis path
  normalized it — the drafted spec's criteria came out clean; only the verbatim `problem` echo carries
  the doubling). The unit test shipped with 0.3.52 called the handler DIRECTLY and passed — the exact
  structure-vs-behavior failure the goal names, in the goal's own tooling. Fix: the handler is now
  REWRITE-ONLY — it mutates `event.text` to the joined form and lets `Input`'s own handler do the single
  insertion (proven through the real dispatch pump before implementing); the regression tests now post
  `Paste` through the message pump, never call the handler directly, and pin the single-line
  never-doubled case. Also observed on this build, working as designed: a fully-enumerated seed produces
  ZERO interview questions (elicit reports no divergence points → research records the objective and
  drafts immediately, per the 0.3.28-era interview-only-on-divergence design) — the operator's review
  point for such a build is `v` before signing. 1355 runtime green.
- **2026-07-01 rev 0.3.53.** **The harness's own model assignments move to the Claude 5 family through a
  single source of truth (§S2 cost-tier posture unchanged; no invariant change).** An inventory found
  exactly four hardcoded `claude-opus-4-8` defaults — `MCPClient` (every parallax/mcp-reasoning call and
  the free-form synthesis/decomposition `complete()`), the developer's code-writing worker, the
  scope-resolver session, and discovery — with no env/config seam anywhere and no tier→model mapping
  (the T0–T3 floors are structural, enforced at dispatch per Invariant 16, orthogonal to concrete model
  choice; the prior posture was uniformly the then-frontier model at all four sites). New
  `runtime/devharness/models.py` `default_model()`: explicit `model=` kwarg > `DEVHARNESS_MODEL` env >
  built-in `claude-fable-5` (the new frontier); all four sites resolve `model or default_model()`
  late-bound at construction. Adversarially reviewed against real source before implementing: no caller
  anywhere passes `model=` explicitly (nothing silently pins the old model), the Agent SDK forwards the
  ID verbatim with no allowlist, and zero docs named the old ID. A new guard test fails if any runtime
  module ever names a concrete model ID outside `models.py`. **Follow-ups flagged, not built:** the two
  cost-tuning candidates the review identified — the high-volume parallax verifier traffic (per-axis ×
  earned-twice) and the retro LLM-residue path (labeled `_RESIDUE_TIER = "T1"` in its own comment yet
  now running frontier) — are where a `claude-sonnet-5` assignment would cut cost most, pending a
  tier→model router design and re-validation of the verdict-parsing paths. Live validation: the next
  operator-driven build runs entirely on the new family. 1355 runtime green.
- **2026-07-01 rev 0.3.52.** **Two more console defects surfaced by the same live build — a silently
  truncating paste and a non-persistent build target that caused real cross-project contamination
  (console UX; +1 event type, EVENT_TYPES 56→57; no invariant change).** **(A) Multi-line paste
  truncation:** Textual's `Input._on_paste` deliberately inserts only `splitlines()[0]` of a paste — a
  two-line project seed pasted into the R prompt was silently cut mid-sentence, twice, forcing the
  elicit interview to open by asking what the truncated sentence meant. The console's `_InputModal` now
  uses a `_JoinPasteInput` subclass that joins pasted lines with single spaces (mirroring the upstream
  handler body otherwise) and toasts "joined N lines" so the operator sees it before submitting.
  **(B) Build target not persisted:** `_target_path` reset to `None` on every console launch, forcing
  re-entry after each restart — and one stale re-entry (the PREVIOUS project's path) landed an entire
  4-task build, branches and final `M` merge included, inside the wrong project's repo; discovered only
  after assembly, remediated by moving the built tool out to its own repo and restoring the clobbered
  README/pyproject. Fix follows the "if an observation matters, it is an event" convention: T now emits
  a registry-only `build_target_set` event (path + test command, correlation `"console"` since T
  precedes any research correlation; no projection, no migration — the `project_assembled` precedent),
  and the console restores the store's latest one on launch. The event store is per-project, so the
  restore is project-scoped by construction. Restore validates the path is still a git repo with a HEAD
  — a stale path is reported, NOT restored, and deliberately NOT re-created (re-running the T-time
  `_prepare_target` would silently resurrect an empty repo at a stale location, which is
  contamination-shaped); an empty stored test command round-trips to None (preserving the
  env-fallback/off semantics), and a restored target's precedence over `DEVHARNESS_TARGET_REPO` is
  logged. Both designs adversarially reviewed against real source (incl. the installed Textual 7.5.0
  handler) before implementing; the review's refinements (always-"console" correlation, `[]→None`
  round-trip, validate-don't-recreate, the join toast) are all incorporated. **Follow-up flagged, not
  built:** a dispatch-time guard warning when the target repo already contains `devharness/*` scratch
  branches from a DIFFERENT correlation — it would have caught this contamination before any branch
  landed. 1349 runtime green.
- **2026-07-01 rev 0.3.51.** **The console (and `run_developer`) now tells the operator when a plan is
  blocked, before it would otherwise be silently skipped (§S2.7 integration; no invariant change,
  observability only).** Live-driving `coverage-check`: a task rejected on a real test failure in the
  built project, `proj_plan.current_state` correctly flipped to `blocked` — but the console's `→ next:`
  hint kept saying "W — build the next task" as if nothing happened, and pressing `W` would have silently
  dispatched the next pending task with zero indication anything needed attention. Root cause: `blocked`
  is set by the `terminal_outcome` projection handler independent of whether `integrate()` ever runs, but
  neither `ConsoleTUI._next_hint()` nor `ConsoleDeveloper._select_task()` (what `W` calls) ever read it —
  both reconstruct state purely from raw `terminal_outcome` events. **Not a new refusal:** rev 0.3.37
  already established that `W`/the driver must advance past ANY terminal, including rejected/aborted —
  refusing reintroduced the exact infinite-hang bug that rev fixed. That rev's other promise — "a
  rejected task is surfaced for operator review" — was never actually implemented in the console (which
  postdates 0.3.37) and only partially in `run_developer.py` (it only warned in the all-settled case, not
  a mid-plan rejection with pending siblings). Fix: `_next_hint()` now checks for a blocked
  (non-completed-terminal) task BEFORE the pending-tasks branch, naming the task_id and its
  reason/detail, and warns explicitly that `W` will skip past it (with the `W <task_id>` retry spelled
  out); `run_developer.py` gets the equivalent print-note. `_select_task`'s intentional
  advance-past-any-terminal behavior is unchanged and now documented inline against exactly this
  regression risk. 1345 runtime green.
- **2026-07-01 rev 0.3.50.** **Research's interview loop now calls parallax `elicit`/`diverge` with the
  real tool schemas, and drops a dead `research` call (R1; no invariant added or weakened — fixes a real
  correctness gap in the operator-facing interview, closes an old unresolved complaint).** Live-driving a
  console research interview surfaced a genuinely blocking symptom: the operator couldn't tell what
  question they were supposed to answer — the `question_asked` event showed a raw JSON dump plus an
  agent's own explanatory prose about a tool-call mismatch, not a clean question. Root cause:
  `roles/research.py`'s interview loop called `elicit(idea=, asked=)` and `diverge(idea=)` against tools
  whose real schemas are `{task, context?}` and `{problem, context?}` respectively — no `idea`, no
  `asked`. Because `MCPClient.call()` dispatches tool calls via a natural-language prompt to a sub-agent
  rather than typed params, the mismatch never hard-failed — a sub-agent silently improvised a mapping
  each time instead, at variable quality. This is almost certainly the root cause of an older,
  previously-unresolved complaint ("same question asked twice... not working as expected") — `asked` (the
  interview round counter) had nowhere to go in the real schema, so it was silently dropped every call;
  `elicit` never actually knew which round it was on. **Fix:** renamed both calls to the real schema, and
  added a local `qa_history` accumulator that threads prior rounds' question+answer pairs through
  `elicit`'s `context` param, so later rounds are informed by earlier ones instead of resurfacing the same
  divergence point. A third call, `research(question=, answer=)`, was deleted outright rather than
  reschematized — its real tool is a costly web-search-and-cite tool with no `answer` param and no
  coherent role in this loop, and its result was never consumed (confirmed dead: only a write-only
  progress counter depended on it). A design-review pass caught that naively truncating the raw JSON
  question payload for `qa_history` would likely feed a broken mid-object fragment back into the next
  round — added `_readable_question()` to extract the actual divergence-point question or assumed
  objective instead. R1's `**Reuses:**` line updated to drop `research`. 1336 runtime green.
- **2026-07-01 rev 0.3.49.** **`feature_spec_claim` gains a 4th axis: the realized diff must add new
  test coverage (§S3 verifier-first acceptance; no invariant added or weakened — closes a real gap in
  what "verified" meant for a feature task).** Checking whether the `a private build` build's features were
  actually tested surfaced that nothing structurally required one: `test_suite` (run pytest, exit 0)
  passes even with zero new tests as long as the pre-existing suite still passes, and `parallax_verify`
  has no test requirement either — a feature could certify with no demonstrating test at all. **Fix:** a
  deterministic (no LLM, "decision rule is code" per this verifier's own stated philosophy) `test_coverage`
  axis scans the realized diff for at least one genuinely NEW `def test_...(`/`class ...Test...` line
  added inside a file that looks like a test file (`_test_coverage.py`); modifying an existing test's
  body without adding a new one doesn't count, blocking trivial-touch gaming. Runs on every feature task,
  not final-task-gated like `spec_criteria` — every task's own diff should carry its own test regardless
  of plan position. A missing-test-coverage failure is exactly as self-correctable as a spec-claim
  deviation, so the bounded auto-retry's retryability check (`verifier/runner.py`) now treats a
  `test_coverage axis` failure the same as a `spec_claim axis` failure; a genuine `test_suite` or
  `spec_criteria` failure stays terminal, unaffected. One prior back-compat behavior no longer holds:
  a feature task verified with no realized diff at all previously fell back to judging the bare claim
  (`test_axis_skipped_without_a_diff`) — an empty diff now always fails at `test_coverage` first, since
  it can add no test by construction; this is the intended effect of having no bypass/escape hatch, not a
  regression. Three research/design/adversarial-review rounds against real source (not just the plan
  text) found and fixed: the regex missed `async def test_...` (a live pattern in this repo's own tests);
  a dead/redundant path-matching clause; and — the most consequential catch — the naive fix for two
  full-loop acceptance tests ("just write another file") would have hard-failed on `ScopeViolation`
  instead, since those tasks declare a single-file `scope_boundary`; both the boundary and the write_hook
  needed widening together. Ten existing test files needed fixture updates once the full suite (not just
  a targeted grep) was run, confirming the review's "floor not ceiling" caveat. 1333 runtime green.
- **2026-07-01 rev 0.3.48.** **External-target branch chaining is now build-order-based, not
  declared-dependency-based (§S3/§S4 developer dispatch; no invariant added or weakened — closes a
  real conflict-causing gap in the console/`run_developer` external-target write path).** Driving a
  console-built project (`a private build`, an external target) through its `M`/assemble step surfaced real
  git merge conflicts: the director's plan had five feature tasks all declare `dependencies: [scaffold]`
  only — a fan-out graph, not a chain, which the decomposition prompt permits (it only requires
  declaring "the scaffold and any prerequisite task," never that every task chain onto its immediate
  predecessor) and which nothing validates the shape of. The existing code cut each external-target
  task's git worktree from `devharness/{task.dependencies[-1]}`, so fan-out siblings never saw each
  other's already-completed work even though the single-writer lock (Invariant 1) means tasks are
  always built strictly serially anyway — three of the five siblings independently edited the same
  shared files, producing real merge conflicts at assemble time that required manual resolution.
  **Fix:** a task's worktree now bases off the branch of whichever task was *actually completed most
  recently in this correlation* (via the `terminal_outcome` event log), excluding any task that is a
  declared descendant of the dispatching task (directly or transitively) — a fresh-context review of
  the design found that a naïve "pure latest-by-seq" version breaks when an upstream/scaffold task is
  re-driven after its dependents already completed (the re-drive's new terminal outranks them by seq,
  which would wrongly chain a later task, or the re-driven task's own next dispatch, onto something
  that logically depends on it — backwards). The descendant exclusion closes that. The declared
  `dependencies` field itself is untouched and keeps its existing uses elsewhere (dispatch/topo-sort,
  the spec-criteria axis's final-task sink-detection, the console's assemble merge-order) — only the
  worktree-seeding logic changed, in `runtime/devharness/console/developer.py` and
  `scripts/run_developer.py` identically. Also landed the same session: the console's `M` (assemble)
  action itself was extended (before this fix) to merge every completed task's branch in dependency
  order rather than refusing any non-linear plan outright (`ConsoleAssemble`, replacing the earlier
  `ForkedPlan` refusal with a `MergeConflict` raised only on a genuine, unresolvable content collision)
  — this chaining fix reduces how often that path is exercised for a real conflict, but the merge-each
  mechanism remains the safety net for whatever residual case still collides. 1324 runtime green.
- **2026-06-29 rev 0.3.47.** **Fourth harness-built artifact — the operator console — + two spec-relevant fixes it surfaced (§S2 non_goals guard, §S4 verifier-first acceptance; no invariant added or weakened — both strengthen fidelity to existing invariants).** The harness built its own operator-facing UI end-to-end through the loop (`runtime/devharness/console/`, `python -m devharness.console`; research → signed spec → a 12-task `mcp-reasoning` plan → all 12 tasks built / verifier-passed / reviewer-certified / integrated): a control surface that drives every operator-gated step with a human in the seat (no LLM agent in the operator decision seat), read-only state from the projections + SSE, every write through `EventBus.emit_sync`, operator-attributed; it adds no new write path, role, gate, or telemetry layer and preserves the sign-off gate, single-writer lock (Inv 1), role boundaries, and earned-twice completion (Inv 5). The build surfaced two **spec-relevant** behaviour defects, each **parallax-validated as the best fix before implementing** (`decide`) and behaviorally proven: **(§S2 non_goals guard)** the parallax conformance check `verify`s an exclusion claim ("the task pursues a non-goal AND serves no success-criterion") that *errors* (`refutation without a named concrete error`) for an in-scope task; the SDK path swallows that tool error to prose, and `parallax_passed`'s prose-scan reads the echoed word "supported" as a verdict → a false deny of an in-scope task (the gate documented as fail-OPEN fell CLOSED). The guard now denies a non-goal pursuit ONLY on an explicit STRUCTURED supported verdict (`parallax_structured_verdict`); an errored or prose-only result is non-affirmative and falls to the deterministic keyword heuristic, restoring the fail-open posture. **(§S4 verifier-first acceptance / Inv 10)** the bounded spec-claim auto-retry (`DEVHARNESS_SPEC_CLAIM_RETRIES`) is now **non-terminal until exhausted**: a retryable spec-claim deviation rewinds clean and leaves the task non-terminal (no `terminal_outcome`), so the next attempt's `queued→running` is legal and exactly ONE `terminal_outcome` is emitted per task (Invariant 10 preserved); only the final, retries-exhausted attempt is a terminal reject. (Previously one reused `TaskLifecycle` carried the terminal `rejected` state across attempts → `TaskLifecycleViolation` on the first real retry — never fired before because every prior project's tasks passed on attempt 1; a naïve reset would have double-emitted a terminal, violating Inv 10.) A third fix — the scaffold's no-direct-write structural test matched the bare word INSERT/UPDATE/DELETE in docstrings — is test precision, not a spec change. Also this session: research **memory-hygiene** (parallax `elicit` consulted its global store and pulled a cross-project Rust lesson into a fresh spec interview — the research role now strips stored-memory items from the elicitation) and the **F7** OSS license-verification prerequisite (fetch + verify the upstream repo's real license against the requester-declared `license_spdx`). The console **IS CI-wired** (`tests/runtime/test_console_*.py`); operator guide at `docs/operator-console-guide.md`. ~1293 runtime green.
- **2026-06-27 rev 0.3.46.** **Sandbox/OSS audit — bounded fixes done, F1/F4/F7 trust-model prerequisites documented (§S4/§S5; no invariant change, security).** A read-only sandbox + OSS-envelope security audit (3 agents, parallax-determined as the highest-value next step) found the sandbox CONTAINMENT sound (the operator-infra adversarial passes held — command injection closed, seccomp x32 + denylist sound, `/mnt/c` closed, mount/pivot correct) but the OSS envelope's TRUST MODEL structurally weak. **Bounded fixes (done):** **F2** — `workflow_guard` now runs on the REALIZED diff (at admission it only saw declared scope globs, and it wasn't even registered in the developer's gate set, so a `.github/**`-scoped task could alter upstream CI/CD unchecked); **F3** — content gates fail CLOSED on an empty/uncomputable realized diff (they passed vacuously); **F5** — `secret_guard` patterns broadened (gh[ousr]_ / fine-grained PAT / GitLab / Slack / Google / JWT) + URL-safe-base64 entropy charset; **F6** — `scope_guard` measures total CHURN not net (delete-and-readd no longer games the reviewability cap); the publish precondition (`_maybe_publish`) is correlation-scoped (plan-local task_ids aren't globally unique — a cross-correlation collision could have published an uncertified branch); sandbox `contained=True` on timeout is now evidence-based (the sentinel must be in the partial stderr) and `/dev/tty` is no longer bound (latent TIOCSTI surface). **Documented as trust-model prerequisites** (`claudedocs/oss-trust-model-prerequisites.md`) — NOT currently exploitable (no real external requester can reach the path; controlled repos only, commitment 14), but gating before the envelope admits real external input: **F1** maintainer "verification" is authorization-against-a-public-list, not authentication (the spoofable trust anchor — real auth depends on the undefined intake channel, so implementing it now would be speculative); **F7** `license_spdx` self-asserted; **F4** injection scanner is a narrow denylist + its broader scan unimplemented. 1093 runtime green.
- **2026-06-27 rev 0.3.45.** **No-plan audit remaining items resolved — enactment + prune input-validation hardening (§S6/§S7; no invariant change, defensive).** Closing the lower findings from the no-plan audit. **(F-enact-1/4)** `is_enactable` now requires a non-empty, non-whitespace STRING signature — a whitespace-only signature cleared antibody_screen's length floor and substring-matched nearly every indented diff line (a DoS on all later work), and a non-string value raised a TypeError in the gate. **(F-enact-2)** `would_weaken_core_gate` normalizes (strip+lower) target_gate/change_kind before membership, so a casing/whitespace variant (`WORKFLOW_GUARD`, ` loosen `) cannot evade the Inv-12 auto-reject (the queue's `target_gate` has no CHECK constraint). **(F-enact-3)** `enact_gate_change` also refuses a non-`is_enactable` change directly (defensive — the sole caller already gates, but the function must not record an inert/arbitrary row). **(prune)** the authorization rejects a whitespace-only `authorized_by`/`reason`. **(F-enact-5, by-design)** `CORE_GATES` is the deliberate seven-gate unweakable set; `antibody_screen`/`non_goals_guard` aren't in it, but a `remove_signature` on them isn't `is_enactable` (can't auto-apply) and goes to operator review. **The broader no-plan audit is now resolved — 3 HIGH (injection) + 1 MED (fail-open) at rev 0.3.44, the enactment/prune items here; prune was otherwise sound (cycles-never-delete, Inv-8 parity, idempotency all hold).** 1088 runtime green.
- **2026-06-27 rev 0.3.44.** **Prompt-injection hardening of the parallax-backed enforcement checks + non_goals fail-open fix (§S2/§S3; no invariant change, security).** A broader audit of the NO-PLAN code (3 agents, security / injection / fail-open classes) found the three high-stakes parallax checks — the `non_goals` guard and `feature_spec_claim`'s `spec_claim` + `spec_criteria` axes — embedded UNTRUSTED text (task description/scope, the realized diff) RAW into their verification claims, so that text could inject instructions that flip the verdict (allow a non-goal task / certify a non-conforming change), defeating the independence of the verification layer. (`llm_residue` was already protected — the asymmetry was that the high-stakes gates were not.) Fix (parallax-validated; an earlier delimiting-only design was REFUTED — delimiters are spoofable and no in-band mitigation is perfect): **(a) context-SEPARATION** — the trusted spec lists stay in the parallax `claim`; the untrusted text moves to the separate `context` parameter (forwarded by `ParallaxVerifyVerifier`), so it is data the verifier consults, never part of the assertion it judges; **(b) defense-in-depth** — a conservative verdict/directive-token scan (`looks_like_prompt_injection`) over the untrusted span fails SAFE (a certify-gate refuses; the non_goals deny-gate falls to the deterministic heuristic). Also fixed the related non_goals **FAIL-OPEN**: an `is_error` parallax RESULT (not a raised exception) previously fell through to ALLOW, bypassing the heuristic backstop — now routed through the heuristic. 1085 runtime green. (Same audit also surfaced, carried lower: gate-change `is_enactable` accepts a whitespace signature → antibody_screen DoS; `would_weaken_core_gate` evadable by `target_gate` casing/whitespace — not enactable; prune whitespace-auth.)
- **2026-06-27 rev 0.3.43.** **Multi-task audit lows resolved — the full audit is closed (§S3/§S5/§S7; no invariant change).** Closing the four LOW findings from the multi-task enforcement audit, all in the re-drive cluster. **Fixed:** the re-drive lifecycle-row inconsistency — `handle_task_started` now clears the prior attempt's `terminal_at_millis`/`outcome`/`reason` on re-entry to `running`, so a re-driven running task is no longer self-contradictory (running + terminal set) and the AuditCycle no longer undercounts it (Inv 8 holds; regression test). **Documented as intentional / accepted residual** (each with rationale, not punted): the OSS intake cooldown counts every submission by design (anti-abuse — throttles submissions, not per-outcome); the `antibody_screen` 3-char floor is a coarse backstop left as-is (the operator's pattern approval is the real guard; a higher floor would reject legit short antibodies like `eval(`); the Brier `(task_id, target_path)` keying collapses a re-driven task's attempts (low-impact calibration telemetry; a precise fix needs a per-attempt marker the write events don't carry). **The full multi-task enforcement audit is now resolved — 2 HIGH + 4 MED fixed, 1 LOW fixed, 3 LOW documented with rationale; spec revs 0.3.36–0.3.43.** 1080 runtime green.
- **2026-06-27 rev 0.3.42.** **Retro queue dedups by (task, kind) — a re-driven task's outcome reaches the learning spine (§S7; no invariant change).** The multi-task audit found the retro scheduler's terminal queue deduped by `source_task_id` alone, so once a task was retro'd, a later terminal (reject → operator re-drive → complete) was never analyzed — the §S7 learning spine permanently saw only the rejection, even after the task succeeded. Fix (parallax-validated, migration-free — `proj_retro_runs` already records `terminal_kind`): the queue dedups by `(source_task_id, terminal_kind)`, so a re-driven task's different-kind terminal (the completion) is analyzed. Residual (accepted, advisory spine): two SAME-kind terminals → only the first analyzed (a same-kind re-terminal carries largely the same signal). Inv 8 parity unaffected (read-side query, no migration). Re-drive regression test added. 1079 runtime green.
- **2026-06-27 rev 0.3.41.** **Inv-5 earned-twice scoped to the current attempt — re-drive soundness (§S3; no invariant change, hardens Inv 5).** The multi-task audit found `can_complete` checked `any(verifier pass) AND any(reviewer cert)` over ALL history by `task_id`, so a re-driven task could earn "done twice" by mixing an EARLIER attempt's verifier pass with the CURRENT attempt's reviewer certification. Latent (the standard loop re-runs both per attempt), but unsound at the check — and Fix A's first-class re-drive (`DEVHARNESS_TASK_ID`) makes it reachable. Fix (parallax-validated; an earlier terminal-boundary design was REFUTED — it breaks when an attempt is abandoned WITHOUT a terminal_outcome): both evidence checks now scope to events after the most recent `task_started` (the attempt-start marker the developer emits on every run; the single-writer lock serialises attempts, so the boundary is unambiguous). Back-compat: no `task_started` → boundary -1 → all events count (unchanged for the non-re-drive path). Cross-attempt regression test added. 1077 runtime green.
- **2026-06-27 rev 0.3.40.** **Fix B scope corrected — the final-task axis checks the diff, not whole-product completeness (§S3; doc-only, no behaviour/invariant change).** The rev-0.3.36 framing over-claimed that the final-task `spec_criteria` axis "validates the cumulative/whole product." The multi-task audit clarified: the axis reads the realized DIFF against HEAD; on a multi-task plan the prior tasks are in that base only because the OPERATOR adopts each completed worktree into HEAD between runs (the §S2.7 integration step — `integrate()` records a disposition, it does NOT git-merge; worktrees detach at HEAD). So the axis verifies the final diff does not VIOLATE a criterion on the operator-assembled base — it is NOT a whole-product COMPLETENESS check (it cannot, on its own, catch a criterion that no task implemented; that is the operator integration gate's job). No behaviour change — the axis already only ever saw the diff; this corrects the wording and documents the adoption dependency + the residual as a real (carried) gap. Comments in `feature_spec_claim.py` + `run_developer.py` corrected.
- **2026-06-27 rev 0.3.39.** **Fix C completed — criteria-awareness on the deterministic + OSS paths (§S2; no invariant change).** The rev-0.3.37 criteria-aware non-goals check was wired only into the parallax path via `run_developer`; the multi-task audit found the deterministic keyword heuristic (the parallax-error fallback) and the entire `run_oss` driver were still criteria-BLIND, so the `--json`-style false-deny persisted there. Fixed: **(3a)** `run_oss` now sets `director._non_goals_parallax` so OSS gets the criteria-aware semantic check (previously every OSS task used the blind heuristic); **(3b)** `keyword_coverage_violation` is now criteria-aware — a task that FULLY covers an enumerated success-criterion is in-scope and is not flagged (full-*criterion* coverage required, parallax-validated as safe for the coarse fallback; distinct from the earlier-refuted weak-overlap veto). Success-criteria threaded into the gate context + the director's parallax-error fallback. 1075 runtime green.
- **2026-06-27 rev 0.3.38.** **OSS reviewer re-run baseline fix — refactor + bugfix verifiers (§S3/§S5; no invariant change).** A targeted multi-task enforcement audit (the csvlite run's follow-up, 3 parallel agents) found the `refactor_behavior_preserving` and `bugfix_regression` verifiers reached their PRE-change baseline ONLY via `git stash` (assuming an UNCOMMITTED change). In the §S5 OSS flow the developer makes the bot-identity commit BEFORE the reviewer re-runs the verifier, so the tree is CLEAN, `git stash` is a no-op, and the captured "baseline" wrongly equalled post: a behaviour-CHANGING OSS refactor certified "preserved" (vacuous PASS, defeating the second Inv-5 check) and a legitimately-fixed OSS bugfix's `baseline_should_fail` axis saw the already-fixed tree and REJECTED (so a fixed OSS bugfix could never ship). Both are OSS-specific — the non-OSS path never commits before the reviewer. Fix (parallax-validated): both verifiers reach the baseline from the CHECKPOINT commit they already hold (`verifier/builtin/_baseline.py` `at_baseline` — stash any uncommitted work, detach-checkout the checkpoint, capture, restore HEAD + stash), robust to a committed OR uncommitted change and a no-op for the non-OSS acceptance run (checkpoint == HEAD). Committed-case regression tests added — the OSS e2e tests stopped at the developer run and never exercised the reviewer re-run (the "green tests certify structure, not behaviour" gap again). 1072 runtime green. (The same audit also surfaced, carried: Fix C incomplete on the deterministic + OSS paths; Fix B's whole-product premise depends on unenforced adoption; an Inv-5 cross-attempt gap on re-drive.)
- **2026-06-27 rev 0.3.37.** **Two more csvlite-surfaced fixes — non_goals_guard criteria-awareness + loop advance-past-terminals (§S2 + the run_developer driver; no invariant change).** Driving csvlite further surfaced two genuine flaws, both **parallax-validated as the best fix before implementing** (an earlier candidate for each was parallax-REFUTED and discarded — a keyword-overlap success-criterion veto, and two-pass corroboration). **(C) non_goals_guard false abort (§S2).** The rev-0.3.33 #3 parallax semantic check stochastically false-positived, HARD-aborting a legitimate `--json` feature task (itself an enumerated spec success-criterion) as a non-goal pursuit. Root cause: the check judged non-goals while BLIND to what is in-scope. Fix: the check is now CRITERIA-AWARE — the spec `success_criteria` are threaded into the parallax claim, and a violation requires parallax to confirm a non-goal pursuit AND that the task serves NONE of the success-criteria (criteria ⊥ non-goals by construction). Live-validated: the `--json` task, previously aborted, now dispatches and completes. **(A) loop infinite-retry of a rejected task (run_developer).** The driver advanced only past `completed` tasks, so a non-completable REDUNDANT task (its behaviour already implemented by a prior task, leaving only a test-only diff the spec_claim axis correctly rejects) was re-dispatched forever, hanging the build. Fix: advance past ANY terminal (completed / rejected / aborted); a rejected task is surfaced for operator review, NOT auto-completed (avoiding a vacuous-test hole); re-driving a specific task is the explicit `DEVHARNESS_TASK_ID` override. The final-task spec-criteria gate (rev 0.3.36) is now keyed on "all other tasks terminal" so a redundant rejection doesn't block it forever. Live-validated: the natural loop advanced past two rejected tasks to the next pending. 1069 runtime green. csvlite has now surfaced FOUR real flaws (two in the recently-shipped #2/#3 enforcement code), each fixed + validated — the third project's validation value.
- **2026-06-27 rev 0.3.36.** **`feature_spec_claim` spec-criteria axis scoped to the final task — incremental-build fix (§S3; no invariant change).** Driving the harness's THIRD project (csvlite) through the loop surfaced that the rev-0.3.33 spec-criteria axis (rev 0.3.34 #4, reviewed "SOUND" but never exercised on an incremental multi-task build) **wrongly rejects an intermediate task**: it checks a single incremental diff against the FULL finished-product `success_criteria`, so task t3 (`--where ==` only) was rejected for a criterion ("all of `== != < <= > >=` supported") that task t4 is designed to satisfy — conflating incremental INCOMPLETENESS with VIOLATION (`!=` raising a clean not-implemented error is not a contradiction). Root cause: a WHOLE-PRODUCT check was bolted onto the PER-TASK verifier. Fix (parallax-verified as the best of four options): the axis enforces **only when the realized worktree IS the complete product** — the FINAL task of the plan (every other plan task already completed+adopted, this diff on top); intermediate tasks skip it. `is_final_task` threads run_developer → verifier (default **True**, so a single-task / standalone plan — the one task IS the product — and the t7 single-task case enforce exactly as before); the per-task `test_suite` + `parallax_verify` (task-claim) axes + the fresh-context reviewer still gate every task. Also added a `DEVHARNESS_TASK_ID` operator affordance to `run_developer` (dispatch a specific task; advance past a non-completable rejected task) — no change to verifier/retry semantics. **Live-validated:** t3, which rejected on the axis, now completes as an intermediate task (axes run = `test_suite` + `parallax_verify`; `spec_criteria` skipped). 1068 runtime green. The "green tests certify structure, not behaviour" thesis again — the axis's unit tests passed; the incremental case was untested.
- **2026-06-27 rev 0.3.35.** **L4-1 — unsandboxed host execution is fail-closed (§S4; no invariant change).** The same audit found the developer's ACI shell (`run_command`, `shell=True`) and test-runner (`run_tests`) ran on the host gated only by an 11-substring destructive blocklist whenever no §S5 sandbox launcher was set — a prompt-injected worker had arbitrary host reach (network exfil, `cat ~/.ssh/...`, absolute-path writes) that the blocklist + realized-diff scope check cannot contain. Fix: `aci/host_exec.py` `require_host_execution_authorized` — the host path now REFUSES (`HostExecutionRefused`) unless the operator opts in via `DEVHARNESS_ALLOW_HOST_SHELL=1` (a trusted-host acknowledgment, commitment 14) or a sandbox launcher is set. The dangerous default is gone: host execution is sandboxed, consciously authorized, or refused. (`run_developer` on a host now needs the flag; the runtime suite authorizes it via `tests/runtime/conftest.py` — the worker is mocked there, so commands are test-controlled.) `test_aci_host_exec.py`; 1066 runtime + 59 specledger green.
- **2026-06-27 rev 0.3.34.** **Audit-found fixes to three of the rev-0.3.33 features (§S2/§S6/§S7; no invariant change).** A no-assumptions audit (3 parallel agents) found real gaps in three of the four rev-0.3.33 features (implemented without a plan); all fixed + tested. **(1) Gate-change enactment scoped (§S7).** The rev-0.3.33 text over-claimed "gates consult the enacted changes" — only the additive `add_signature` kind has a live consumer (`antibody_screen`), while the deterministic spine emits only `tighten`/`loosen` signals on `verifier_attached_gate`/`cost_mode_gate`, which carry no auto-applicable parameter. Fix: `approve_gate_change_candidate` auto-enacts only an `is_enactable` change (`add_signature`); the rest are approved operator decisions the operator applies, so `proj_enacted_gate_changes` holds only what is actually in effect (never an inert row). **(2) `non_goals_guard` over-block (§S2).** The wired parallax path treated ANY non-affirmative verdict (uncertain / abstain / tool error) as a violation and aborted the task; the claim is now inverted ("this task PURSUES a non-goal") so a deny requires parallax to AFFIRMATIVELY confirm a pursuit — an unsure verdict lets the task proceed, matching the gate's conservative contract. **(3) prune wrong-row (§S6).** `trust_grant_pruned` now carries `grant_row_id` and the handler deletes by that PK, not the non-unique natural key `(role, class, granted_at_millis)` — a same-millisecond sibling grant (one later renewed) is no longer collaterally deleted. 1060 runtime + 59 specledger green. The fourth feature (the `feature_spec_claim` spec-criteria axis) was reviewed SOUND.
- **2026-06-27 rev 0.3.33.** **Four post-rollout enforcement behaviours documented — the code led; this realigns the spec (§S2/§S3/§S6/§S7; no invariant/governing-layer change, the 18 hold).** A no-assumptions code-level audit closed four genuinely-open gaps, each wired (not inert) + tested + committed, the live-LLM paths validated with real parallax; they were implemented **without a spec edit first** (an operator-flagged process deviation), so this revision realigns the source-of-truth. **(1) Gate-change enactment (§S7).** The learning spine's gate-change half had been approved-but-inert while the antibody half was live; an approved gate-change now enacts into `proj_enacted_gate_changes` via the `gate_change_enacted` event (the sole enactment path, mirroring `antibody_added`), and gates consult it (`antibody_screen` screens enacted `add_signature` patterns). A core-gate weakening can never be enacted (Inv 12, re-checked at enactment). Migration **0026**; `retro/enacted_gate_changes.py`. **(2) Operator-authorized prune (§S6).** The maintenance cycles stay read-only (advisory); actual removal of expired trust grants is a separate operator-authorized action — `devharness prune` → one `trust_grant_pruned` per expired grant (event-sourced delete, replay-safe), requiring an authorizer + reason. Expired grants are already invalid at use, so tidiness, not correctness; the §S6 'cycles never delete' invariant still holds (the prune is outside the cycles). `maintenance/prune.py`. **(3) Non-goals guard (§S2).** A planned task pursuing the signed spec's non-goals is denied at dispatch by a new admission-time gate `non_goals_guard` — a deterministic keyword-coverage heuristic plus an injectable parallax-backed semantic check the live director wires (parallax-error degrades to the heuristic). +1 adversarial probe (the every-enforcing-gate-has-a-probe invariant; 12→13). Closes the prior gap where the decompose prompt *saw* the non-goals but nothing enforced a plan stayed within them. `gates/non_goals_guard.py`. **(4) `feature_spec_claim` spec-criteria axis (§S3).** A third verifier axis: the realized diff must not VIOLATE any enumerated spec `success_criteria`, checked via parallax independently of the task's own tests — closing the t7 coverage gap where a spec deviation certified twice-earned-done (the prior two axes saw only the task's tests + a one-line claim). The criteria are threaded run_developer → verifier → reviewer; additive (no criteria → the prior 2-axis behaviour). EVENT_TYPES 52 → **54** (`+gate_change_enacted`, `+trust_grant_pruned`); migrations 0021–**0026**; **13** gates; 1057 runtime + 59 specledger green. **No invariant change** — these realize existing design intent (an enforced learning spine, spec-faithful verification). Live-validated with real parallax: #2's axis passed a clean jqlite `--version` feature (no false-positive → certified); #3's parallax path denied a `rich`-dependency task at dispatch the heuristic provably missed.
- **2026-06-26 rev 0.3.32.** **OS-resource accounting — `resource_snapshot` event + `resource_health` tile (§S9 25→26).** The harness had rigorous event accounting but no visibility into the OS *resources* it consumes (processes, worktrees, memory), which is how a `git fsmonitor--daemon` leak (per-task worktree churn orphaning detached daemons) grew unseen until process pressure tripped the Agent SDK's 60s init timeout. `runtime/devharness/health.py` (`system_snapshot`, stdlib-only, every probe degrades to -1) captures a cheap reading the drivers emit as a `resource_snapshot` event per task (EVENT_TYPES +1 → 52); `run_developer` prints it + a pre-flight `leak_warning` when the git-process count is abnormally high. The `resource_health` tile renders the per-task series so growth shows on the dashboard. Pairs with the source-level fixes (create_worktree disables `core.fsmonitor`; run_developer prunes terminal-task worktrees; `test_worktree_leak` guards both). No invariant change (C7 re-enforced at 26; the 18 hold).
- **2026-06-26 rev 0.3.31.** **§S9 tile manifest: 7 feedless B0 generic placeholders removed (32→25).** The original 12 generic projection tiles (one per `0002_projections.sql` table) included 7 — `proj_spec`, `proj_plan`, `proj_cost`, `proj_antibody_queue`, `proj_gate_change_queue`, `proj_lock`, `proj_boot_parity` — with no feeding event type, so they rendered a permanent "no live event feed" placeholder. B1–B5 added dedicated *named* tiles (Drafted/Signed specs, Plans, Candidate Queue, Antibody Library, Lock & checkpoints, …) that show the same state from real events, so the 7 placeholders were dead duplicates sitting above the real tiles. Removed from the §S9 manifest, `dashboard/src/tiles.js`, and `dashboard/src/tiles/registry.js` in sync (C7 stays green — `check_dashboard_tile_coverage` is derived). The 5 generic tiles that *do* have a live feed (`proj_role_state`/`proj_task_queue`/`proj_review`/`proj_gate_fires`/`proj_terminal_outcomes`) remain. The projection *tables* themselves are untouched (§Data model, the handlers, and the runtime still use them). No invariant change (C7 re-enforced at 25; the 18 hold). Driven by the operator catching the dead tiles live on the dashboard.
- **2026-06-26 rev 0.3.30.** **§Governing Layer commitment 3 narrowed — the per-role budget claim retired** (governing-layer change; accompanies constitution v0.2.0). Commitment 3 was "Context is a finite budget with declared sources. Each role gets a declared budget and declared sources"; it is now "Context has declared sources" (the `setting_sources=[]` posture). The per-role *budget* half was vacuous in practice — the per-role spec registry (`roles/base.py:registered_roles`) the budget boot check iterated was never populated (roles grew their own `run()` loops, not `spawn_role`), and the live cost model is per-task caps (`oss/caps.py`) + the director's per-task tier minima (§S2/§S8), not a per-role budget. The §Capabilities cost-model line is correspondingly "per-task cap bounds", not "per-role budget bounds". This spec edit reconciles the source-of-truth with the **constitution v0.2.0 amendment** (which dropped `check_role_context_budget_declared` from C3's claim set — boot ledger 24→23, Inv-18 parity held) and the code (the dead `roles/base.py` substrate — `RoleSpec`/`spawn_role`/`RoleWorker`/the registry — was deleted; `AgentRole`/`progress_from_messages`/the `BudgetExceeded` exception retained). The amendment was driven against the harness's own tech-debt register (#H8/#C5) and `parallax decide`. No invariant change (the 18 hold).
- **2026-06-25 rev 0.3.29.** **The feature/refactor class can now `complete` — three more stacked verifier/reviewer fixes** (§S3 + R4; no invariant change). After rev 0.3.28 (#C0) three further bugs, each hidden behind the last, still blocked every feature from completing. **(C0b)** `parallax_passed` required the WHOLE rendered parallax output to equal a single pass-word, so a genuine `supported (confidence 1.0)` verdict — prose or JSON — always scored as fail; it now parses the verdict from either shape (`verifier/builtin/_common.py`). **(C0c)** `test_suite` scored a test-runner launch-crash (Windows `0xC0000142` under process pressure, no test output) as a failed test and rewound good work; a launch-crash is now retried, a persistent one raised as an infrastructure error, never a `VerifierFailed` (`verifier/builtin/test_suite.py`). **(C0d)** the reviewer (R4) built its claim from bare identifiers (`"task X completes spec Y per plan Z"`, no diff), which parallax refuses for lack of evidence, so the Inv-5 "done earned twice" second half could never be earned for a feature; the reviewer now forwards `spec_claim` + the realized `diff_content` (objective artifacts; the fresh context still bars the developer's session) (`roles/reviewer.py`). With #C0/C0b/C0c/C0d fixed, the harness **completed its first feature end-to-end through the enforced loop**, live-validated on `specledger --list-checks` (developer acceptance → reviewer certification → `terminal_outcome=completed`). The feature class was blocked by four stacked bugs, each hiding the next. Detail in `claudedocs/tech-debt-register.md`.
- **2026-06-24 rev 0.3.28.** **#C0 — `feature_spec_claim` verifies the realized diff, not the proposal** (§S3; no invariant/governing-layer change). The verifier ran `parallax.verify(spec_claim)` where `spec_claim` is the task description — a forward-looking "implement X" proposal that parallax correctly refuses as unverifiable without evidence, so it **rejected every real feature** (surfaced by running #M2 as a live feature task: the worker's code passed the test_suite axis, but the proposal axis failed). Now, when the verifier context carries `diff_content`, the parallax axis embeds the realized unified diff as evidence and asks parallax whether the diff delivers the claim; the `test_suite` axis (real behaviour) is unchanged, and a context with no diff falls back to the bare claim (back-compat). `run_developer.py` supplies `developer._realized_diff(worktree)`. `test_feature_spec_claim_c0.py`. **Unblocks the feature/refactor task classes**, which previously could never `complete` through the loop.
- **2026-06-24 rev 0.3.27.** **Bounded tech-debt remediations #H6 / #M5 / #H9** (no invariant/governing-layer change). *#H6 (§S3):* `run_developer.py` dispatches the task's attached `verifier_ref` (the director's per-class verifier) instead of a hardcoded `test_suite`, with a context carrying the fields the per-class verifiers read + a real parallax client; `new_project_scaffold` (no `verifier_ref`) still falls back to `test_suite`, and the fresh-context reviewer re-runs the same verifier. *#M5:* `test_cli_subprocess.py` runs the operator CLIs as the real `python -m` subprocess and asserts the projection updates — catching a `main()`-level regression (no `__main__` guard / a registry-less bus) that the inner-function tests miss. *#H9 (§S9):* the sidecar's `EVENT_CATALOG` is now **derived** from the Python registry (`manifest.py` also writes `sidecar/src/event_catalog.generated.rs`; `lib.rs` `include!`s it) — it was hand-frozen at 7 of 49 types, neutering the `/audit/dead-events` L10 audit for 42; `test_event_catalog_rs_derived.py` guards drift in the Python job. 954 Python + 6 Rust green.
- **2026-06-24 rev 0.3.26.** **The boot suite actually runs at boot (#C4)** (tech-debt remediation; no invariant/governing-layer change). The audit found nothing iterated `_REGISTRY` and *called* the 24 checks — "fail-closed at boot" was emergent from per-check unit tests, and the `_ok` no-op default would have silently passed an unmapped check. `boot.run_boot_checks(conn=None, registry=None)` now executes every registered check (dispatched generically by signature), failing closed (`BootError`) on any check that returns non-`True` or raises; the three `scripts/run_*.py` drivers call it after `migrate`, before any work. `_ok` is replaced by `_unmapped`, which **raises when called** — an unmapped claim name now fails closed instead of vacuously passing. `test_boot_suite.py`. **Carried (#C5):** `check_setting_sources_empty` / `check_role_context_budget_declared` are now *executed* at boot but remain vacuous against the empty role registry — making them assert the live roles is bundled with removing the dead `roles/base.py` substrate (#H8).
- **2026-06-24 rev 0.3.25.** **OSS content gates fire on the realized diff (#C1/#C2)** (post-validation tech-debt remediation; no invariant/governing-layer change). A layered debt audit (`claudedocs/tech-debt-register.md`) found that `secret_guard` (content axis) and `scope_guard` (cumulative-LOC) read `diff_content`, which the director never populated — so the OSS secret-scan and LOC limit **passed vacuously on every real contribution** (the same mock-boundary class as the earlier #7). `DeveloperRole._enforce_content_gates` now runs them in-lock on the realized worktree diff (`is_oss` only); a deny rewinds clean + emits `gate_fired`, and the director emits `terminal_outcome(rejected)`. §S4 updated; `test_oss_content_gates.py` (secret + over-LOC denied, clean passes, non-OSS skipped). First of the register's CRITICAL remediations.
- **2026-06-24 rev 0.3.24.** **Local-developer sandbox tier wired (#1a)** (no invariant/governing-layer change). The ACI `ShellActions.run_command` + `TestRunnerActions.run_tests` route through a §S5 `SandboxLauncher` when `DeveloperRole(sandbox_launcher=…)` is set (opt-in; default `None` = host execution, back-compat) — the **first actual use of `SandboxLauncher.exec` in command execution** (B4.2.5 shipped the launchers + the availability gate but never routed commands through them). §S4 updated. **Residual (carried):** launcher FS-confinement depth (WSL still exposes `/mnt/c`; seccomp deferred) + the Windows↔WSL env mismatch — full local confinement wants the worker to run end-to-end in the Linux sandbox. Mechanism unit-tested (`test_sandbox_routing.py`). **All three post-specledger maturity gaps (#2a/#2b/#1a) are now implemented; the §Post-B5 open items are operator-driven verifications + organic refinements only.**
- **2026-06-24 rev 0.3.23.** **Research spec-body synthesis (#2a) + director spec→task decomposition (#2b) implemented** (the rev 0.3.22 carried improvements; no invariant/governing-layer change). Both add an injectable free-form `complete()` on the MCP client (`mcp/base.py`) and compose JSON that is **strictly validated**, with a **safe fallback to the prior behaviour** on any malformed / non-JSON output — synthesis only ever upgrades the result. *(#2a, §Architecture R1/research)* `ResearchRole._synthesize_body` asks parallax to compose `scope` / `non_goals` / `interfaces` / `success_criteria` / `verification_plan` from the operator idea + interview assumptions; `_draft_and_persist(body=…)` uses it, else templates the body as before. *(#2b, §Architecture R2/director)* `DirectorRole._decompose_spec` asks mcp-reasoning to decompose the signed spec into a validated BUILD task list (each `task_class` ∈ the five BUILD classes, `scope_boundary`/`dependencies` well-formed); `run()` uses it when no `tasks=` are injected, else the single-task default. Shared helpers in `roles/synthesis.py` (`extract_json` / `parse_spec_body` / `parse_task_list`). **Carried:** #1a local-developer sandbox tier; live end-to-end validation of the synthesized spec/plan *quality* (the mechanism + fallback are unit-tested).
- **2026-06-24 rev 0.3.22.** **Post-specledger-validation follow-ups** (the first-project validation run surfaced these; no invariant/governing-layer change). **Implemented:** *(1b, §S4)* the developer worker runs with the built-in write/exec tools (`Bash`/`Write`/`Edit`/`MultiEdit`/`NotebookEdit`) in `disallowed_tools` — the only write path is the ACI, even under `bypassPermissions`. *(2c, §Architecture R4)* the reviewer's **default** verifier set is now `test_suite` (the universally-applicable independent re-run) rather than the fixed claim-based 4-set, which misfired on a `new_project_scaffold` cert (no computable claim / no verbatim sources → `parallax_grounded_verify` falsely rejects); claim-bearing tasks pass `CLAIM_VERIFIERS`. **Spec'd improvements (design resolved; focused implementation carried):** *(2a, §S1/research)* the research role should **synthesize** the spec body (scope / non-goals / interfaces / success-criteria) from the operator interview via a parallax/LLM compose-and-validate pass — today `_draft_and_persist` fills only the `assumptions` list and templates the rest, so operator intent reaches the developer through assumptions only. *(2b, §S2/director)* the director should **decompose** a signed spec into its task list via mcp-reasoning (validated structured output, single-task fallback) rather than taking an injected `tasks=` list or a generic default. *(1a, §S4)* route the **local** (non-OSS) developer through the §S5 `SandboxLauncher` tier for out-of-worktree host containment. Each lands behind its own green CI matrix when implemented; the specledger validation worked around 2a/2b by the operator supplying interview answers + the task decomposition.
- **2026-06-24 rev 0.3.21.** **§S4 realized-diff scope enforcement** (post-B5, surfaced by the specledger first-project validation run). The developer's `scope_boundary` is now enforced on the **realized worktree diff** after `_run_worker`, not only on ACI editor tool-calls: a worker that wrote via the ACI shell (`run_command`) or built-in tools bypassed the per-write `scope_gate` and `write_attempted`/`write_applied` tracking (the specledger scaffold landed correct + test-passing with **zero** editor write events). `DeveloperRole.run()` computes `git status --porcelain -uall` (gitignore excludes build artifacts), checks each changed path against `scope_boundary` (same `fnmatch` rule); on any out-of-scope path it rewinds `clean=True` and the director emits `terminal_outcome(rejected, reason="scope_violation:…")` (skipping verifier/review); in-scope non-editor writes are tracked with `write_applied(action_kind="worktree_diff")`. No invariant/governing-layer change — this *realizes* Inv 1's scope intent rather than altering it. **Carried:** out-of-worktree host writes need the §S5 sandbox tier; disallowing built-in write/exec tools is a defense-in-depth follow-up.
- **2026-06-24 rev 0.3.20.** **B5 closure — the §S7 learning spine, as built** (implementation-plan v0.8.9, B5 closed at `a0537c9`). Documents the design choices B5 surfaced; no invariant/governing-layer change (audit **18/0/0 — full graduation**; Inv 11/12/17 graduated at B5.2/B5.3/B5.5). **Learning spine (§S7).** The retro auditor fires on **every** `terminal_outcome` (completed + rejected + aborted) inside the B3.6 maintenance window, fermata-gated, deduped by `source_task_id` (OQ-B5-1=A, revisitable to the rejected/aborted subset via the `RetroScheduler._next_unprocessed` filter if blocking-review noise overwhelms). The engine is **compositional** (OQ-B5-4=C): a deterministic **T0 pattern-matcher** runs first (no LLM, no injection surface — `PATTERN_SIGNATURES`: gate-deny/intake-reject → antibody, verifier-fail/cap/Brier-drift → gate-change); the **unmatched residue** routes to an LLM only on T0-empty contexts, behind the §S7 injection quarantine + a `CORE_GATES` structured-output filter. CANDIDATEs route to `proj_antibody_queue` (text-only learnings) or `proj_gate_change_queue` (code-changing proposals) and **never auto-apply** (SC-2). **Gate-change validator.** A CANDIDATE that would weaken a core gate (`loosen`/`remove_signature` on a `CORE_GATES` member) is auto-rejected *before* operator review (A-SYS-5, Inv 12): the projection handler sets `review_state='rejected'` durably (a weakening candidate is never observable as `pending`), and `GateChangeRejected` is an **event-log-only audit** record (`auto_rejected=True`). `CORE_GATES` (the seven enforced gates) is the **single source of truth** — the same frozenset object imported by both the validator and the LLM filter (identity-checked). Core-gate *tightening* is allowed. **Operator review.** **Blocking** (OQ-B5-2=A, revisitable): a CANDIDATE stays `pending` until an explicit approve/reject; no auto-archive, no TTL. The `candidate_reviewed` event drives the queue transition (`reviewed_by`/`reviewed_at_millis`); approve publishes via the approval pipeline, reject also emits `candidate_rejected` (audit). CLI: `devharness retro list-pending | approve | reject` (reviewer identity from `DEVHARNESS_OPERATOR_ID` else OS user). The §S9 `candidate_queue` tile surfaces pending counts. **Antibody library.** **Text only** (Inv 11): the only payload is `pattern_text`; no callable / code / eval column (structural — the boot check introspects the structs *and* the table schema). Populated solely via operator-approved CANDIDATEs through the approval pipeline (`antibody_added` is emitted from exactly one place — the SC-2 single-emitter guard). `match_against_text` exists but is not wired into any gate by default. **Cross-project trusted memory.** **Federated** (OQ-B5-3=B): each project carries its own `proj_memory`; cross-project sync is explicit operator-driven export/import. An imported entry is **untrusted** (`verified_locally=0`) until `verify_memory_entry` promotes it with verifier evidence (Inv 17); locally-created entries start trusted. Import is idempotent on `entry_id` and **monotonic** per `source_project` (an entry older than the latest known is rejected — a downgrade-attack guard); export omits verification state so each project verifies independently. An approved antibody bridges into local trusted memory. **Dashboard event-list derivation (§S9).** The dashboard's SSE dispatch list is **derived** from the Python `EVENT_TYPES` registry at build time (`events/manifest.py` → `events.generated.js`, imported by `events.js`) — the B4.7 SSE-wiring gap class is eliminated structurally, not re-checked per event; CI fails on drift (`test_events_js_derived.py`, in the Python job since the consistency check needs registry access). EVENT_TYPES 36 → **49**; migrations **0021–0025**; **32** tiles.
- **2026-06-24 rev 0.3.19.** **B5.6 learning-spine dashboard visibility** (implementation-plan v0.8.7). §S9 tile manifest **28 → 32**: adds `candidate_queue` (the antibody + gate-change review queues — pending counts, recent reviews/rejections, validator-auto-reject vs operator-reject distinction), `antibody_library` (active-library size + recent additions + revoked count), `retro_activity` (recent `retro_run`s — T0-matched-signatures vs LLM-residue proportion), `trusted_memory` (local `proj_memory` entries + their `verified_locally` state; imported-pending-verification surfaced). C7 re-enforced at 32. **SSE-wiring hygiene (closes the B4.7 gap):** the dashboard's event-dispatch list is now **derived** from the Python `EVENT_TYPES` registry (`runtime/devharness/events/manifest.py` → `dashboard/src/events.generated.js`, imported by `events.js`); CI fails on drift (`test_events_js_derived.py`). No invariant/governing-layer change (audit stays 18/0/0 — full graduation reached at B5.5). Records the B5.0–B5.5 learning-spine landing: retro engine, antibody library, gate-change validator, blocking operator review, federated trusted memory; EVENT_TYPES 36 → 49; migrations 0021–0025.
- **2026-06-24 rev 0.3.17.** **B4 closure** (implementation-plan v0.7.6, B4 closed at `4cab232`). Records the design choices B4 surfaced; no invariant/governing-layer change. **§S5 OSS envelope:** the four C1 fear-map gates (`workflow_guard`, `secret_guard`, `scope_guard` cumulative-LOC, `sandbox`) all graduated to real bodies; `secret_guard` is **two independent axes** — path-based (file-name globs) + content-pattern (diff scan), each with its own override (rev 0.3.14); the §S2 `oss_contribution` row stays **deferred** (OQ-B4-2: OSS is an envelope layered onto the BUILD classes via the `is_oss` flag + `oss_envelope`, not a standalone class). **Intake hardening:** SPDX license allowlist + maintainer verification + context-injection scan + requester cooldown, each refusing before planning. **Per-task caps:** wall-clock + USD via `enforce_caps` polled in the director dispatch loop (aborts the in-flight `is_oss` task on breach); requester cooldowns (rate-limit) + operator revocation, carried on the reused `budget_exceeded` event with a `budget_kind` discriminator (OQ-B4-3). **Commit-identity split:** OSS commits carry a distinct bot identity (`DEFAULT_OSS_COMMIT_IDENTITY`, per-upstream override), committed after the verifier passes (§S4, rev 0.3.16). **Fork-branch worktree** off the upstream `target_branch` with OSS scope tightening. **Sandbox launcher (multi-tier, OQ-B4-2-environment):** a `SandboxLauncher` interface with three bindings — `MockSandboxLauncher` (CI + non-Linux, fail-closed), `WSLSandboxLauncher` (real namespace isolation on the dev box), `VPSSandboxLauncher` (remote Ubuntu over SSH) — behind a `SANDBOX_LAUNCHERS` registry; WSL auto-selected when present, VPS opt-in via `preferred="vps"`; CI runs mock-only. SC-3 structurally enforced by the `sandbox` gate (deny when mock-only) and behaviorally verified against real WSL containment (`claudedocs/sc3-acceptance.md`); the VPS path is operator-driven (carried to B5 open items). Audit 15/0/3; 24/24 boot-check bodies real; 28 dashboard tiles.
- **2026-06-24 rev 0.3.16.** B4.5 commit-ordering fix (surfaced by the B4.8 acceptance). §S4 gains the **OSS lock-held-through-verifier extension**: for `is_oss=True` tasks the lock is held through worker → verifier → (conditional) bot-identity commit, the verifier runs against the *uncommitted* worktree (so stash-baseline verifiers reach their baseline), and the OSS identity commit lands only on `VerifierOk` — the fork-branch never carries unverified commits (verifier-first, C2). The prior ordering (commit in `developer.run` before the verifier in `complete_task`) both broke `bugfix_regression`/`refactor_behavior_preserving` and committed unverified work. `DeveloperRole` gains an `oss_verify_fn` seam that runs the OSS verifier in-lock before the commit; reviewer cert + terminal still run unlocked. No invariant/governing-layer change. The B4.8 acceptance is restored to OSS feature + OSS bugfix.
- **2026-06-23 rev 0.3.15.** B4.7 OSS-envelope visibility. §S9 tile count 25 → **28**: three new tiles — **oss_intake** (`oss_task_intake`/`intake_decision`), **oss_enforcement** (`budget_exceeded` filtered to the OSS `budget_kind` variants), **oss_branch** (`oss_worktree_created`/`commit_identity_assigned`) — added to the C7 tile manifest. The C7 boot-check (`check_dashboard_tile_coverage`) re-enforces at 28 (spec manifest == `dashboard/src/tiles/registry.js`). Also records the B4.7 wiring of `enforce_caps` into the director's dispatch loop (the per-task caps poll that aborts an in-flight `is_oss` task on a wall-clock/USD breach — the B4.6 follow-up). No invariant/governing-layer change.
- **2026-06-23 rev 0.3.14.** secret_guard reconciliation (B4.2, parallax `decide` Option B, score 86 vs 68, confidence 0.59). §S5 `secret_guard` is now **two independent axes — defense in depth**: a **path axis** (secret-named-file globs, the original §S5 intent) AND a **content axis** (the B4.2 diff pattern-scan), each with its own override (`secret_guard_path_override` / `secret_guard_content_override`). Either axis triggering denies, so a contributor must evade both vectors (named-file AND embedded-pattern). This reconciles the B4.2 divergence (the shipped content scan was stronger but had dropped the original path coverage and the no-override posture): rather than revert (Option C, 34) or keep content-only (Option A, 68), B4.2 adds the path axis back alongside content and gives each axis an override — consistent with the workflow_guard/scope_guard/sandbox override pattern. Evidence carries matched path list + pattern names + line count, never the secret text. No invariant/governing-layer change; the gate's REQUIRED_GATES membership + the C1 boot-check are unchanged. Accompanies implementation-plan v0.7.4.
- **2026-06-23 rev 0.3.13.** OSS-as-envelope (B4 planning, OQ-B4-2). The §S2 `oss_contribution` row is **marked deferred** — B4 resolved (parallax `decide`, OSS-flagged composition, score 74 vs 54, confidence 0.6) to model an OSS contribution as an **`is_oss=True` BUILD task** (`feature`/`bugfix`/`refactor`/`dependency_bump` against an external repo), not a standalone task class. The four §S5 fear-map gates (`workflow_guard`/`secret_guard`/`scope_guard`/`sandbox`) **layer additively** onto the BUILD class's gate profile when `is_oss=True`; the class's B3 verifier is reused unmodified; per-class Brier + trust keep keying on `(role, task_class)`. The §S5 envelope is a *safety* concern, not a *verification* shape. No invariant/governing-layer change; the §S5 envelope contents (gates, sandbox, intake, caps, identity) are unchanged — only the task-class framing moves from a standalone class to a flag on the BUILD classes. Accompanies implementation-plan v0.7.2 (B4 decomposition).
- **2026-06-23 rev 0.3.12.** B3 closure. Marked **B3 complete** (status line + rollout ladder; closed at `975d7b7`): the four existing-repo BUILD classes (`feature`/`bugfix`/`refactor`/`dependency_bump`) each with its own verifier, the §S6 maintenance loop (fermata-paced, flat-cost `maintenance` class), and the adversarial self-tester (known-bad probes per gate, run in the maintenance window) all landed and were exercised by the B3.9 cut-line acceptance pass. The **Playwright 25-tile browser re-verify** (5× deferred across B1.7/B2.9/B2.10/B3.8/B3.9) was **cleared at closure**: a live headless-Chromium render of the dashboard against a sidecar fed a full B0+B1+B2+B3 sequence confirmed all 25 tiles render, the 2 B3 tiles (maintenance + adversarial) show their feed data, and the adversarial tile surfaces a regression prominently — no page errors. Audit unchanged: 15 invariants real / 0 partial / 3 phase-tagged skip (Inv 11/12/17 are B5); EVENT_TYPES 34; registry 24 boot-check names (the 4 C1 OSS-gate stubs land in B4). No invariant/governing-layer change. Accompanies implementation-plan v0.6.2.
- **2026-06-23 rev 0.3.11.** §S9 maintenance + adversarial tiles: B3 expands the dashboard 23 → 25 with the **maintenance** tile (← `maintenance_tick`/`maintenance_action`, §S6) and the **adversarial** tile (← `adversarial_test_run`/`gate_regression_detected`), both added to the parseable tile manifest the C7 boot-check enforces against `dashboard/src/tiles/registry.js` (fail-closed on divergence). No invariant/governing-layer change. Accompanies B3.8 (maintenance + adversarial dashboard tiles; C7 re-enforced at 25).
- **2026-06-23 rev 0.3.10.** B2 closure. Documented four design choices B2 surfaced, each in the sub-system it touches: §S1 — trust is event-sourced (`trust_granted`/`trust_renewed`/`trust_revoked`) and projected to `proj_trust_grants` with Inv 8 parity; §S3 — `Verifier.verify` is async, `run_verifier` is the supported sync↔async entry point (direct `verify()` calls discouraged); §S4 — `rewind_to(clean=True)` runs `git clean -fd` after `git reset --hard` for a fully-clean rejected-task worktree, plus the **lock-release semantics** (lock held during the write phase only; verify/review/terminal run unlocked because read-only; released when `DeveloperRole.run()` returns). No invariant/governing-layer change. Accompanies the B2 closure (implementation-plan v0.5.2, B2 closed at `ca7d7a5`): 15 invariants real / 0 partial / 3 phase-tagged skip (Inv 11, 12, 17 are B5); 19 of 24 boot-check names have real bodies (the 4 C1 OSS-gate stubs land in B4); the full write loop is verified end-to-end (research → sign → plan → dispatch → write → verify → certify → integrate).
- **2026-06-23 rev 0.3.9.** §S9 write-phase tiles: B2 expands the dashboard 18 → 23 with five new tiles (developer_activity, verifier_outcomes, reviewer_certs, lock_checkpoint, trust_state) and their feeding event types, plus a parseable **tile manifest** the C7 boot-check (`check_dashboard_tile_coverage`) enforces against `dashboard/src/tiles/registry.js` (fail-closed on divergence). No invariant/governing-layer change. Accompanies B2.9 (write-phase dashboard tiles; C7 graduates).
- **2026-06-23 rev 0.3.8.** OQ5 (reviewer composition) resolved: **single parallax-backed reviewer**, chosen over a bruno-swarm specialist panel by a parallax `decide` (score 78 vs 66, confidence 0.56 — moderate). §Architecture R4 updated — the reviewer runs as one Agent SDK worker subprocess per certification, fresh context (zero inherited history, `setting_sources=[]`), read-only tool inventory (parallax verify/check/grounded_verify + ACI read/run_tests; no write actions). §Open Questions OQ5 marked resolved, with the specialist-panel pattern noted as a **revisitable** future tightening candidate given the moderate confidence. No invariant/governing-layer change. Accompanies B2.5 (ReviewerRole + certification; Inv 2 graduates). OQ2 (developer form factor) fully resolved: the single writer takes the **Agent SDK worker** form, resolved over a headless Claude Code session by a parallax `decide` (score 84 vs 42, confidence 0.71). §Architecture R3 updated — the developer is a runtime-driven subprocess with `setting_sources=[]`, MCP-scoped tools (parallax + mcp-reasoning + the in-runtime `devharness-aci` ACI server), cwd = its isolated worktree, per-call cost runtime-tracked; the ACI's structured write actions replace raw Edit/Write/Bash and are gate-checked per write. §Open Questions OQ2 marked resolved. No invariant or governing-layer change. Accompanies B2.3 (DeveloperRole + ACI + worktree isolation). B1 closure housekeeping — documented two design choices B1.6 surfaced, with no invariant or governing-layer change. §S9 now records the **events-as-SSE payload denormalization** rule: because the dashboard renders only from the SSE stream (never querying projections), a field a tile must show is denormalized into its event payload even when an artifact also holds the source-of-truth — `SpecSigned` gained `signed_at_millis` and `ExplorePassCompleted` gained the file/manifest/test/ci counts as the B1.6 examples. §Data model (Projection schemas) now records the **no-AUTOINCREMENT** convention: projection surrogate keys use a plain `INTEGER PRIMARY KEY` so a DELETE+replay rebuild reproduces rowids and Invariant 8 parity holds, plus the pre-production rule that empty placeholder tables may be DROP+CREATEd but data-holding tables need ALTER/CTAS. B1 marked complete (implementation-plan v0.4.2, closed at `576a540`). Recorded the B1 tightening calls (tracing to parallax `decide` recommendations) into the spec surface they touch: §S9 tile count 12 → 18 with the six named research-flow tiles (questions, assumptions, draft spec, signed spec, plan, explore summary) and their feeding event types; §Open Questions OQ2 (developer form factor) marked partially resolved — advisory roles take the Agent SDK worker form, the developer form factor stays open until B2. (The three remaining tightening calls — event-payload discriminators, CLI sign-off, standard explore-pass output shape — are implementation-plan detail, landing in plan v0.4.1.) Note: the amendment request labeled the form-factor question "OQ3" under the pre-rev-0.3.1 numbering; under the current numbering it is OQ2.
- **2026-06-22 rev 0.3.4.** Documented two design choices surfaced building and accepting B0: §S9 now records (a) the sidecar's permissive `tower-http` CORS layer enabling cross-origin browser SSE, and (b) the dashboard's single shared `/events/all` connection with client-side demux, mandated by the browser HTTP/1.1 ~6-connections-per-host limit (the per-tile design starved the 7th stream in the B0.8 render). No invariant or governing-layer change; B0 substrate marked complete.
- **2026-06-21 rev 0.3.3.** Reverted commit `f18712a`'s §S5 "defense in depth" clarification (the sentence that the four OSS fear-map gates ship in REQUIRED_GATES at B0 boot). The base §S5 line "all fail-closed and in REQUIRED_GATES from boot" is retained; the gates are now scheduled into the implementation plan at B0.5 (plan v0.2) as part of the 22 boot-check stubs rather than asserted from first boot in prose.
- **2026-06-21 rev 0.3.2.** Added §Data model — event catalog and projection schemas: seven typed event payloads (`msgspec.Struct`, frozen, kw_only, `schema_version=1`) — `connection_opened`, `role_transitioned`, `intent_proposed`, `gate_fired`, `verifier_outcome`, `checkpoint_taken`, `terminal_outcome` — and concrete `CREATE TABLE` DDL for the 12 dashboard projection tables. §S9 points to the new section. Conventional field/column names chosen at this rev. Runtime mirrors land in `runtime/devharness/events/registry.py` and `schema/migrations/0002_projections.sql` (B0.4). Status parenthetical updated from "no code authored" to "B0 substrate in progress" (B0.0–B0.3 had landed).
- **2026-06-20 rev 0.3.1.** OQ1 (Name) resolved to devharness; placeholder note removed and OQs renumbered.
- **2026-06-20 rev 0.3.** Resolved the two open spec-level items from the rev 0.2 review using parallax `decide`. **Item 1 (Invariant 18):** tightened from count-only to 1:N name-mapped; each commitment declares a claim set of one or more boot-check function names, and CI asserts every commitment's set is present in the registry and that no boot check is unmapped. **Item 2 (director tier):** adopted Option C, per-task-class director tier minimum. Added a director-tier-minimum column to the §S2 task-class table with B1/B2-provisional placeholders (≥T0/≥T1/≥T2). Folded the director into §Definitions as a sibling orchestrator role to advisory. Extended Invariant 16 to bound budget and tier and to refuse below-floor dispatch with a `director.tier_floor_violation` event. Updated §S8, R2 constraints, the §Governing Layer amendment paragraph, SC-10, OQ4, and the B0 rollout to reference the new shape.
- **2026-06-20 rev 0.2.** Incorporated external code-agent review. Resolved former OQ2 to four roles (D1) with accepted-cost noted. Added Invariant 16 (director reasoning budget bounded at dispatch), Invariant 17 (trusted memory carries a verification event), Invariant 18 (constitution/enforcement parity + amendment version bump). Clarified Invariant 1 vs §S4 (lock governs developer sessions; worktrees serial, never parallel). Separated declared verification from reviewer certification in §S3, Invariant 5, and the R4 note. Added `refactor` and `dependency_bump` task classes with gate profiles. Pinned SC-5 to Brier ≤ 0.15 (B2-ratified). Added the T0–T3 / call_class / advisory-role glossary (§Definitions). Noted `workflow_guard` GitHub-specificity in §S5 and Assumptions. Reworded the downstream-repos audience as observed, not sentient. Spelled out Invariant 14's single-source-of-truth test. Added the constitution drift gate to §Governing Layer. Narrowed former OQ5/OQ6 into OQ4/OQ5.
- **2026-06-18 baseline draft.** First complete devharness spec, synthesized from `developer-agent-harness-brief-revised.md` and the internal corpus.
