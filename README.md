# sizzy

A phased agent harness for collaborative software development - verifier-first acceptance, a single-writer lock, an OSS-contribution envelope, and a learning spine, all under operator-in-the-loop discipline.

sizzy is not a general agent framework. It is a specific harness: four roles with structurally-enforced tool boundaries drive an event-sourced loop - research → spec → plan → write → verify → review → integrate - where every consequential step is earned, not asserted. A task is `completed` only when a declared verifier passes **and** a fresh-context reviewer certifies it (two separate checks). Gates fail closed. Retro proposals never auto-apply; an operator approves or rejects each one. Core safety gates cannot be weakened by the learning loop. These are invariants with tests, not prompt requests.

The harness also carries a **learning spine**: every terminal outcome feeds a retro auditor that proposes improvements (antibodies, gate changes) as CANDIDATEs into operator-review queues, plus federated cross-project memory under verified-before-trusted promotion.

## Architecture

Three processes over one SQLite file:

- **`runtime/`** - the Python harness. An append-only, hash-chained **event log** is the single source of truth; `EventBus.emit_sync()` is the sole writer. Read models (projections) are rebuildable from the log by DELETE+replay, and a parity test asserts the rebuild reproduces them exactly (Invariant 8). Roles, gates, verifiers, the single-writer lock, checkpoint/rewind, the OSS envelope, and the learning spine all live here.
- **`sidecar/`** - a Rust (axum + tokio + bundled SQLite) SSE relay that tails the event log and multiplexes it to the dashboard over a single CORS-enabled `/events/all` stream.
- **`dashboard/`** - a Svelte 5 dashboard of 28 live tiles, each subscribed to the `/events/all` stream. The dashboard renders strictly from the event stream (it never queries projections).

Two load-bearing properties:

- **Verifier-first acceptance (done is earned twice).** A `completed` terminal requires a passing verifier *and* a fresh-context reviewer certification - separate checks, both required.
- **Gates fail closed.** A gate denies a known-bad intent before any write; denies (and allows) carry structured evidence. The four §S5 OSS gates plus the write-lock, spec-signed, and verifier-attached gates are the seven **core gates** the learning loop can never weaken.

The four roles and their enforced boundaries:

| Role | Can | Cannot |
|---|---|---|
| Research | read / research, fan-out sub-agents | repo writes |
| Director | dispatch, plan, reasoning | any file write |
| Developer | hold the single write lock; edit/commit in one isolated worktree | write outside its task scope |
| Reviewer | read, parallax verify/check, run tests | any write/edit/commit |

## Safety

Parts of the harness spend real money and can make changes outside this repository:

- **The drivers and panel actions spend real LLM money.** `scripts/run_*`, the operator console,
  and the web panel dispatch Claude Agent SDK sessions billed to your Claude login or API key. A
  multi-task build can cost tens of dollars.
- **The rev-0.4.0 overage fallback rebills your API key.** When a subscription's weekly quota is
  exhausted, `sdk_query.run_query` retries the call once with the `ANTHROPIC_API_KEY` configured in
  `~/.claude.json` - deliberate, so a drive doesn't die mid-loop, but it means quota exhaustion
  silently shifts spend to metered API billing.
- **`run_oss.py` opens real GitHub PRs** (when `GH_TOKEN` + `DEVHARNESS_OSS_PUSH_REPO` are set). It
  is operator-only by design.
- **The web panel is a write surface with no auth of its own.** It binds loopback by default and
  must never face a network without an authenticating reverse proxy (TLS + basic auth - see
  `deploy/vps/`). Its request gate (Host/Origin validation) stops cross-site abuse, not
  authenticated access.
- **The write loop requires two operator-local MCP servers** - `parallax` and `mcp-reasoning`
  (separate repositories, not bundled here). Without them the research/director/reviewer paths do
  not run. Publishing those servers is a separate decision by their owner; this repo only documents
  the boundary.

See **`SECURITY.md`** for the full security posture - the fail-closed host-shell guard, the sandbox
tiers, the panel's CSRF-only request gate, and how to report a vulnerability.

## Quick start

Requirements: Python 3.11+, a Rust toolchain, Node.js.

```bash
# Python runtime (editable install with test extras)
cd runtime && pip install -e ".[test]" && cd ..

# Rust SSE sidecar
cd sidecar && cargo build --release && cd ..

# Svelte dashboard
cd dashboard && npm install && cd ..
```

Run the test suite; the acceptance tests drive the full loop end-to-end:

```bash
pytest tests/runtime -q -n auto             # ~1570 tests (from the repo root; parallel-safe)
pytest tests/specledger tests/jqlite tests/csvlite -q   # the three in-repo projects' own suites (~646)
cd sidecar && cargo test
cd dashboard && npm run check
```

> Note: the root `pyproject.toml` belongs to the **jqlite** subproject - `pip install .` at the
> repo root installs jqlite, not the harness. The harness runtime installs from `runtime/`.

Run the dev stack (dashboard):

```bash
# terminal 1 - the sidecar relays the event log over SSE
./sidecar/target/release/sidecar
# terminal 2 - the Svelte dashboard
cd dashboard && npm run dev
```

> **Driving the loop.** There is no single "dispatch a task" command, but `scripts/` holds live operator drivers that run each stage against a real project: `run_research.py` (spawns the research role on a one-line seed, runs the operator interview, synthesizes + persists a spec), `run_director.py` (plans the signed spec - set `DEVHARNESS_DIRECTOR_DECOMPOSE=1` to let the director decompose it), `run_developer.py` (the scope-contained write loop), `run_oss.py` (the §S5 OSS envelope, operator-only), `run_maintenance.py` (the §S6 maintenance window + the §S7 learning-spine retro pass), and `run_discover.py`/`run_promote.py` (issue discovery → spec promotion). Operator gates are spec sign-off and (early) integration; the operator-facing CLIs run as modules: `python -m devharness.cli.{sign,answer,retro,memory}`. The drivers clear a stray `ANTHROPIC_API_KEY` at startup so the Agent SDK uses the claude.ai login. The end-to-end shape is also exercised by `tests/runtime/test_b5_acceptance.py` and the per-phase acceptance tests.
>
> **Operator console.** A human-driven control surface over the same operations. `python -m devharness.console` launches an interactive **TUI** - a live loop-state panel plus keypress actions for the whole loop: the immediate operator decisions (sign/reject/review a spec, integrate, accept/reject a retro candidate, prune, enact a gate-change) **and** the long-running build steps (research, director plan, developer dispatch, certify, OSS), each run in a background worker with live event-by-event progress. It **switches between projects (`P`) and starts new ones (`N`) without quitting** - each project is its own event store, and the console reconnects in place rather than forcing a relaunch with a different `DEVHARNESS_DB`. It degrades to a read-only snapshot in a non-TTY context or without the `[tui]` extra. `python -m devharness.console status [--follow]` is the one-shot snapshot. Underneath, `runtime/devharness/console/` exposes every gated step (research, sign-off, director, developer, review/integrate, the loop decisions, the OSS path) as an operator-attributed action through `EventBus.emit_sync` - a human in the operator seat, no LLM agent making loop decisions. See **`docs/operator-console-guide.md`**. The console was itself built end-to-end through the harness's own loop (research → signed spec → a 12-task plan → all 12 tasks).

## Key concepts

- **Event log** - append-only, hash-chained events; the single source of truth and the only telemetry (no separate observability layer).
- **Projections** - derived read models rebuilt from the log; rebuild parity is an invariant.
- **Gates** - fail-closed checks that deny a known-bad intent before a write, carrying structured evidence.
- **Verifiers** - per-task-class pass/fail acceptance checks (feature spec-claim, bugfix regression, refactor behavior-preserving, dependency resolves, …).
- **Roles** - research / director / developer / reviewer, each a separate enforced tool surface.
- **Task classes** - `new_project_scaffold`, `feature`, `bugfix`, `refactor`, `dependency_bump`, plus `maintenance`; each declares its gate profile and verifier.
- **OSS envelope (§S5)** - the layer an `is_oss` task routes through: intake hardening, the four fear-map gates, a fork-branch worktree, a bot-identity commit after the verifier passes, per-task caps + cooldowns.
- **Retro / learning spine (§S7)** - every terminal outcome feeds a retro auditor that emits CANDIDATEs into operator-review queues; nothing auto-applies.
- **Antibodies** - text-only known-bad patterns, added only via operator-approved CANDIDATEs.
- **Memory** - federated cross-project memory; imported entries are untrusted until locally re-verified.

## Project structure

```
runtime/      Python harness - events, projections, gates, verifiers, roles
              (incl. synthesis), task_classes, lock, worktree, checkpoint,
              retro, memory, oss, sandbox, console (the operator-facing UI)
sidecar/      Rust SSE relay (axum) tailing the event log → /events/all
dashboard/    Svelte 5 dashboard - 28 live tiles over the SSE stream
schema/       forward-only SQL migrations (0001–0028)
specledger/   the harness's first project - a stdlib repo-consistency checker
jqlite/       the second project - a stdlib jq-style JSON query CLI (all 5 BUILD classes)
csvlite/      the third project - a stdlib jq-style CSV query CLI (10-task plan)
              (the fourth harness-built artifact is the operator console, in runtime/devharness/console/;
              console-driven external projects live OUTSIDE this repo: a private build, a private build, a private build,
              a private build, a private build - eight real projects through the loop in total)
scripts/      live operator drivers (run_research / run_director / run_developer / run_oss /
              run_maintenance / run_discover / run_promote)
specs/        the phased implementation plan
docs/         the operator-console user guide
tests/        the test suite (tests/runtime, tests/specledger, tests/jqlite, tests/csvlite)
              (the spec lives at the repo root: devharness-spec.md)
```

## Deeper docs

> **A note on the docs:** `CLAUDE.md` is agent/contributor context (architecture, conventions),
> not end-user setup documentation. Commit SHAs cited in the docs refer to the private pre-release
> history (the public repository starts from a fresh initial commit), so they will not resolve here.

- **`CLAUDE.md`** - agent/operator context: architecture-at-a-glance, the rollout ladder, conventions, and current state.
- **`devharness-spec.md`** (rev 0.4.15) - the canonical specification: governing layer, architecture, event-sourced spine, sub-systems §S1–S9, the 18 invariants, acceptance criteria, rollout, open questions (all resolved). The source of truth; when code disagrees with the spec, the spec was wrong.
- **`specs/implementation-plan-v0.1.md`** (v0.9.14) - the phased decomposition B0–B5, the resolved open questions, the §Post-B5 open-items block, and the what-shipped revision history (incl. the real projects + the operator-console build + the post-rollout hardening + the audits). The current-status record.
- **`docs/operator-console-guide.md`** - how to drive the loop yourself from the operator console (the human-in-the-seat control surface).
- **`.specify/memory/constitution.md`** (v0.2.0) - the 13 governing commitments and their boot-check claim sets.
- **`CONTRIBUTING.md`** - conventions (each enforced by a test or invariant) and how to add a gate / event type / task class.
- Component READMEs: `runtime/README.md`, `sidecar/README.md`, `dashboard/README.md`.

## License

MIT - see `LICENSE`.
