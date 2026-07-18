# Contributing to devharness

devharness is governed by a spec and a set of invariants, each with a test. The conventions below are not style preferences — most are enforced by a test or a boot check, and a change that breaks one fails CI. When in doubt, the order of authority is: **spec → invariants/tests → existing code**. Design changes land as spec edits first (with a revision-history entry), then code.

## Non-negotiables (operator-in-the-loop)

These are structural guarantees, not configuration:

- **No auto-apply (SC-2).** A retro CANDIDATE never enacts itself. The only path from a CANDIDATE to an applied change is an explicit operator approve/reject. `antibody_added` is emitted from exactly one place (the approval pipeline) — a structural single-emitter guard.
- **Core gates are unweakable by retro (Inv 12).** A CANDIDATE proposing to weaken a core gate (`loosen`/`remove_signature` on a `CORE_GATES` member) is auto-rejected at the validator, before operator review.
- **Done is earned twice (Inv 5 / C2).** A `completed` terminal requires a passing verifier **and** a fresh-context reviewer certification — separate checks.
- **The reviewer runs in a fresh context (C11).** Zero inherited history, read-only tools.

## Conventions (each enforced by a test or invariant)

- **Handlers are pure projections.** A projection handler takes `(conn, event)` and writes only to its projection table. It must not emit events (it has no `event_bus`) and must not depend on another handler's side effects. When durable state and an audit event are both needed, the producer emits the event and the handler projects it (the B5.3 rule; e.g. `gate_change_rejected` is event-log-only audit while the queue's `review_state` is set durably by the candidate handler).
- **Gates fail closed, with structured evidence.** A gate denies a known-bad intent before any write; denies carry a structured evidence dict (the B4.2 pattern), and allows may carry evidence too (the B4.3 symmetric API).
- **The single-writer lock governs the write phase only.** One developer holds the lock; worktrees are serial under it. For OSS tasks the lock is held through worker → verifier → (conditional) commit (the B4.5 ordering: commit only after the in-lock verifier passes).
- **Event types are declared in `runtime/devharness/events/registry.py`.** The dashboard's dispatch list is **derived** from this registry (`events/manifest.py` → `dashboard/src/events.generated.js`), so there is no second list to keep in sync.
- **No `AUTOINCREMENT` on projection tables.** Projection surrogate keys use a plain `INTEGER PRIMARY KEY` so a DELETE+replay rebuild reproduces rowids and Invariant 8 parity holds.
- **Forward-only, numbered migrations.** Under `schema/migrations/` (`0001`–`0028`); the runner fails closed on a gap or out-of-order version. Pre-production, empty placeholder tables may be DROP+CREATEd, but data-holding tables need ALTER/CTAS. Each new migration breaks the three ledger-idempotency tests until its version is appended to their `applied_versions` assertion.
- **`setting_sources=[]` for any Agent SDK invocation.** No silent inheritance of CLAUDE.md or settings into agent sessions.
- **The event log is the telemetry.** If an observation matters, it is an event. No additive observability layer.
- **Test-affordances are explicit and default-off.** A production class may carry a test-only seam (e.g. `DeveloperRole(write_hook=…)`, `clear_task_classes()`) that is a no-op in production. A class whose name starts with `Test…` but is not a test sets `__test__ = False` so pytest does not auto-collect it (e.g. `aci/test_runner.py`).

## Operational invariant (dev-stack teardown)

**Never `taskkill //IM node.exe //F`** when tearing down the local dashboard. The Playwright MCP server itself runs as a `node.exe` process; a blanket node kill drops the MCP. Tear down with `taskkill //IM sidecar.exe //F` plus the **vite PID by port** (`netstat -ano | grep ":5173" | grep LISTENING` → `taskkill //PID <pid> //F`).

## How to add a new gate

1. Implement it in `runtime/devharness/gates/` (fail-closed; deny carries a structured evidence dict).
2. Register it via the gate module's side-effect import / the gate registry.
3. Add a known-bad probe in `runtime/devharness/adversarial/probes.py` (the adversarial self-tester runs one probe per gate in the maintenance window).
4. If it backs a constitution boot-check claim, graduate the boot-check stub to a real body when ready.
5. If it is one of the seven **core gates**, add it to `CORE_GATES` in `retro/gate_change_validator.py` — the single source of truth shared (by identity) with the LLM residue filter.

## How to add a new event type

1. Declare a `msgspec.Struct` in `runtime/devharness/events/registry.py` (`frozen=True, kw_only=True, schema_version=1`; validate non-empty fields in `__post_init__`; use `Literal[...]` for enumerated fields) and add it to `EVENT_TYPES`.
2. Add a projection handler in `runtime/devharness/projections/handlers.py` only if state needs persisting (keep it a pure projection; add the table to `PROJECTION_TABLES` if it is rebuilt by the parity DELETE set).
3. Regenerate the dashboard dispatch list: `npm run generate-events` (or `python -m devharness.events.manifest`) and commit `dashboard/src/events.generated.js`. `test_events_js_derived.py` fails CI on drift.

## How to add a new task class

1. Register a `TaskClassSpec` in `runtime/devharness/task_classes/builtin.py`.
2. Bind its gate profile in `runtime/devharness/task_classes/gate_binding.py`.
3. Wire its `verifier_ref` so the director plans it with the right per-class verifier.

## Tests

- Tests live in `tests/runtime/`; follow the existing layout (a `_setup()` building an in-memory DB + registry + `EventBus`, one assertion-focused test per behavior).
- The CI matrix is three jobs: **python** (`pip install -e ./runtime[test]` + `pytest tests/runtime -q -n auto`, plus the in-repo projects' suites: `tests/specledger`, `tests/jqlite`, `tests/csvlite`), **rust** (`cargo test`), **svelte** (`npm run check`). All three must be green on push.
- A new migration must be appended to the three ledger tests' `applied_versions`. Event counts are derived, not pinned — after adding an event type, regenerate the dashboard dispatch list (`npm run generate-events`) and commit `events.generated.js`; `test_events_js_derived.py` fails CI on drift.
- Every invariant has a named test in `tests/runtime/test_invariants.py`; the audit is currently 18 real / 0 partial / 0 skip. Do not regress it.

## Commits

- Feature branches only; do not commit directly to `main` for substantive work.
- Incremental commits with meaningful messages; reference the sub-phase or open-question ID where relevant (e.g. `B5.7`, `OQ-B5-3`).
- Diff before staging; commit before risky operations.
