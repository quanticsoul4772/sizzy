# Operator console — user guide

The operator console (`runtime/devharness/console/`, run with `python -m devharness.console`) is the
control surface for driving the devharness write loop **yourself**, with a human in the operator seat
instead of an LLM agent. It exposes every operator‑gated step of the loop as a direct action and
reflects loop state read‑only from the event‑sourced projections.

It is the harness's own first‑class artifact: research → signed spec → a 12‑task plan → all 12 tasks
built, verified, reviewer‑certified, and integrated through the loop. This guide is how you use it.

## What it gives you, and what it never does

- **Every gated step as an action:** start research and answer its interview, sign or reject the spec,
  dispatch the director to plan, dispatch the developer to write a task under the single‑writer lock,
  advance reviewer certification and integration, and make the loop decisions (task accept/reject,
  retro CANDIDATE approve/reject, prune authorization, gate‑change enactment), plus the §S5 OSS path.
- **One write path.** Every state change goes through `EventBus.emit_sync` (the `cli/_bus`
  `projected_bus` writer). The console **never** writes the event store or a projection directly, and
  it issues the *same* operations the `run_research` / `run_director` / `run_developer` / `run_oss`
  drivers and the `devharness retro` / `prune` CLIs already perform.
- **Your decisions are attributed to you.** Actions take an `operator=` argument recorded on the event.
- **The invariant boundaries stay enforced:** the operator sign‑off gate, the single‑writer lock
  (Invariant 1), the role tool boundaries, and earned‑twice completion (Invariant 5) all still fire —
  the console is a control surface, not a new authority. It adds no new write path, role, gate, or
  telemetry layer.

## Quick start — run the TUI

`python -m devharness.console` launches an interactive **TUI** (Textual): a live loop‑state panel on
top, an output log below it, and a keymap along the footer. Install the optional UI extra once —
from the repo root, `pip install -e "runtime[tui]"` (the package is local‑only, not on PyPI) —
point it at an event store with `DEVHARNESS_DB` (default `var/devharness.db`), and run it:

```bash
# bash / zsh
DEVHARNESS_DB=var/devharness.db python -m devharness.console
```
```powershell
# PowerShell
$env:DEVHARNESS_DB="var/devharness.db"; python -m devharness.console
```

> **Prefer an absolute `DEVHARNESS_DB`** (or launch from the repo root): a relative path resolves
> against your current directory. The console resolves it to absolute and tells you; a missing parent
> directory **fails closed** naming the resolved path, and creating a brand‑new store is announced
> loudly (`⚠ created NEW EMPTY event store at …`) so a typo can't silently start a parallel history.

**The screen.** The top panel shows live loop state (active role, signed spec, task counts, event
count); it follows the sidecar's SSE stream and falls back to polling when the sidecar isn't running.
The log panel below it prints the result — or the exact error — of each action you take.

**Doing things.** Press a key (below). If the action needs input, a prompt box opens — type the
value(s), **separated by spaces**, and press Enter (Escape cancels). Example: press `x` to reject a
spec, then type `spec-7 scope is wrong` — the spec id, then the reason.

> **Don't memorize the keys** — press **Ctrl+P** for the command palette, a searchable list of every
> action. (The footer also lists keys, but it truncates on a narrow window; the full set is here.)

| key | action | the prompt asks for |
|---|---|---|
| `r` | refresh the state panel | — |
| `v` | review a spec (opens a scrollable viewer; Escape closes) | `spec_id` |
| `s` | sign a spec | `spec_id` |
| `x` | reject a spec | `spec_id reason…` |
| `i` | integrate a task | `task_id` |
| `c` | view pending retro candidates (scrollable viewer; Escape closes) | — |
| `a` | accept a candidate | `queue row_id` |
| `j` | reject a candidate | `queue row_id reason…` |
| `p` | view expired trust grants (viewer) | — |
| `k` | prune expired grants | `reason…` |
| `g` | view approved gate‑changes (viewer) | — |
| `e` | enact a gate‑change | `row_id` |
| `q` | quit | — |

The **list** actions (`c`, `p`, `g`) open the rows in the same scrollable viewer `v` uses (an empty
list is just a one‑line log entry). Keys are inert while the viewer is open, so the rhythm is:
list → read the `row_id`s → **Escape** → act (`a`/`j`, `k`, `e`).

### The build steps (Shift + letter)

The long‑running LLM steps run in a background worker so the UI stays responsive; their event‑by‑event
progress streams into the upper **progress panel**. They need a **file‑backed** `DEVHARNESS_DB` (a
build step against `:memory:` is refused).

> **The panel guides you.** The top line of the state panel — `→ next: …` — always tells you what to
> press next (sign / plan / build / answer / done) based on where the loop is. And most prompts accept a
> **blank** input that defaults to the **latest** spec / correlation / question — so you can drive the
> whole loop with just keypresses, no copying 32‑char ids.

| key | step | input (blank = the latest) |
|---|---|---|
| `T` | set the build target (where a new project builds) | `<repo_path> \| <test command>` |
| `R` | start research (drafts a spec from an idea) | your idea / seed |
| `A` | answer the current research question | your answer (the question is auto‑selected) |
| `D` | director — plan the signed spec | `correlation_id` — blank = latest |
| `W` | developer — write one task | `correlation_id [task_id]` — blank = latest, next pending task |
| `C` | certify a task (fresh‑context reviewer) | `task_id` |
| `O` | OSS — run the §S5 contribution path | `correlation_id` |
| `P` | switch to another project (no quit) | a list number or a store path |
| `N` | start a new project (store + target + research in one) | `name \| repo_path \| seed` |
| `ctrl+x` | cancel the running step (best‑effort) | — |

Only one build step runs at a time (the title bar shows which). **Research is interactive:** press `R`
with an idea; each question shows in the progress panel AND in the `→ next` line, and `A` auto‑selects
it — just type your answer. A complete, unambiguous seed gets **one confirmation turn** instead of an
interview: research shows what it's about to build and its assumptions; reply `ok` to proceed, or type
a correction and it threads into the spec. Repeat until the spec drafts — then sign (`s`) and plan
(`D`). Cancel (`ctrl+x`) is **best‑effort** — it abandons the result, but an in‑flight LLM run can't be
force‑stopped; quitting (`q`) is refused while a step runs, so the write lock is never stranded.

### Switching projects and starting new ones (no quit)

Each project is its own event store (`var/<name>.db`). You do **not** need to quit and relaunch with a
different `DEVHARNESS_DB` to change projects:

- **`P` — switch project.** Lists the stores beside the current one (each as `store → target repo`);
  type the list number (or a full `.db` path) and the console reconnects to that store and restores its
  target. Refused while a build step is running (finish or `ctrl+x` first).
- **`N` — new project.** One prompt — `name | repo_path | seed` — creates `var/<name>.db`, sets the
  build target to `repo_path` (with `python -m pytest -q`; change it later with `T`), and starts research
  on the seed, all in one action.

> **Sidecar note:** switching is clean on the no‑sidecar path (the solo‑operator default — the state
> panel follows the new store immediately). If you're running the SSE sidecar, it tails a *fixed* store,
> so the *progress* pane keeps showing the launch store's events until you restart the sidecar; the state
> panel and your builds are unaffected.

### Building a new project (set a target first)

A new project builds in **its own clean git repo**, verified by only its own tests — not inside
devharness. Use **`N`** for the one‑shot (store + target + research together), or the manual order
**`T` → `R` → `s` → `D` → `W`** (the `→ next` line walks you through it):

1. Press **`T`** and enter `<repo_path> | <test command>` — e.g. `../dedup | python -m pytest -q`
   (prefer an absolute path; relative paths resolve from where the console was launched). If the path
   doesn't exist, `T` **creates it, `git init`s it, seeds a cache‑covering `.gitignore`, and adds an
   initial commit** for you — no separate setup. The active target shows in the state panel, **persists
   across restarts** (restored on launch; a stale/deleted path is reported, not resurrected), and T
   **warns if the repo carries scratch branches from correlations this store has never seen** — the
   signature of pointing at another project's repo by mistake (warning only; a deliberate re‑target
   is fine).
2. Then `R` (research) → `s` (sign) → `D` (plan) → `W` (build, repeat per task) → **`M` (assemble)**. The
   developer builds in that repo and the verifier runs your test command **there** — only the project's
   own tests.

**Where the result lands:** each certified task is committed onto a `devharness/<task_id>` branch in the
target repo, whether the plan is a strict-sequential chain or has parallel/fan-out tasks (several tasks off
one shared dependency). When `→ next` reads `M — assemble`, press **`M`** — it merges every completed
task's branch into the target's main, one at a time in dependency order (recorded as a single
`project_assembled` event), so the finished tool lands in the working tree without leaving the console.
Re-pressing `M` on an already-merged build is a no-op. Assemble refuses until every task is `completed`,
and an internal devharness build has nothing to assemble. If two tasks' branches genuinely collide on the
same lines of the same file, `M` aborts the in-progress merge and reports `MergeConflict` naming the task —
that one case still needs a manual `git merge`/conflict resolution.

**The scaffold must produce at least one passing test.** A `pytest` run that collects *zero* tests exits 5,
which the verifier scores as a failure — so the first task's spec/seed should ask for a smoke test.

Pressing `W` with **no** target set is **refused** — set `T` first, so a build can't accidentally land
inside devharness (the footgun: `W` before `T`). To build devharness itself, set `T` to its own path.

**Non-Python targets (Rust / JS / Go).** The harness does **not** auto-detect the toolchain — the test
command you give `T` is what the verifier and the worker run, so for a non-Python project set it there:
e.g. `../hello-rs | cargo test`, `../tool | go test ./...`, `../pkg | npx jest`. That command threads to
the scaffold verifier, the feature `test_coverage`/`test_suite` axes, and the worker's self-test, and the
`test_coverage` axis reads the command's language to detect the ecosystem's tests (Rust `#[test]`, JS
`it(`/`test(`, Go `func Test…`) instead of Python `def test_`. Two target-setup notes for these: the
scaffold task's scope must cover the ecosystem's files (`**/*.rs` + `Cargo.toml`, or `package.json`, etc.
— name them in the spec/seed so the director's scope isn't Python-shaped), and the seeded `.gitignore`
should exclude the build tree (`/target`, `/node_modules`) — the harness purges an untracked `target/`
before the scope check (the Rust build-output case), but a project-level ignore is the norm and is what
covers `node_modules/`.

### The read‑only snapshot

`python -m devharness.console status` prints a one‑shot text snapshot and exits (this is also what a
bare invocation falls back to in a non‑TTY context, or without the `[tui]` extra installed):

```
=== devharness operator console ===
active role: (none)
spec: signed 65313259f8a24f6ab49d42e8f7ebd626 by <operator>
tasks: completed=12
events: 410
```

Add `--follow` to block on the live SSE stream (from the sidecar) and re‑render on every event:

```bash
DEVHARNESS_DB=var/devharness.db python -m devharness.console status --follow
```

## The model

Everything hangs off one connected app:

```python
from devharness.console.app import ConsoleApp

app = ConsoleApp(db_path="var/devharness.db").connect()   # opens + migrates the store, arms emit_sync
app.render()        # the text snapshot above
app.loop_state()    # a LoopState: active_role, spec_signed, signed_spec_id, signed_by, tasks_by_state, event_count
```

`app.connect()` opens the SQLite event store, brings it to the current schema, and arms the
`EventBus` writer. Each operator action is its own accessor off `app`:

| Accessor | Action object | Key methods |
|---|---|---|
| `app.research(operator=…)` | `ConsoleResearch` | `start_research(topic)`, `ask_question(research_id, text)`, `submit_answer(question_id, answer)` |
| `app.signoff(operator=…)` | `ConsoleSignoff` | `review(spec_id)` → dict, `sign(spec_id)`, `reject(spec_id, reason)` |
| `app.director()` | `ConsoleDirector` | `plan(correlation_id, spec_id=…, tasks=…, reasoning=…)` |
| `app.developer(**kw)` | `ConsoleDeveloper` | `dispatch(correlation_id, task_id=…, spec_claim_retries=2)` |
| `app.review()` | `ConsoleReview` | `certify(task_id, …)` → bool, `integrate(task_id, …)` |
| `app.task_decision(operator=…)` | `ConsoleTaskDecision` | `list_pending(queue=…)`, `accept(queue, row_id)`, `reject(queue, row_id, reason)` |
| `app.retro(operator=…)` | `ConsoleRetro` | `list_pending(…)`, `approve(queue, row_id)`, `reject(queue, row_id, reason)` |
| `app.prune(operator=…)` | `ConsolePrune` | `list_expired()`, `prune(reason)` |
| `app.enact_gate_change(operator=…)` | `ConsoleEnactGateChange` | `list_approved()`, `enact(row_id)` |
| `app.oss(**kw)` | `ConsoleOss` | `run(correlation_id, envelope=…, …)` |

> Two ways to drive it: the **interactive TUI** (`python -m devharness.console`, Quick start above) now
> covers the whole loop with keypresses — both the immediate operator decisions and the long‑running
> build steps (research / director / developer / certify / OSS). The **Python API** below is the same
> action layer programmatically — use it to script the console or embed it.

## Drive a project end‑to‑end

A correlation id scopes one project's events; pick any stable string (e.g. `myproj`).

```python
from devharness.console.app import ConsoleApp

app = ConsoleApp(db_path="var/myproj.db").connect()
CID = "myproj"
ME  = "your-name"

# 1. Research — start a session and answer its interview questions.
research = app.research(operator=ME)
research_id = research.start_research("A stdlib-only CLI that …", correlation_id=CID)
# The research role asks questions; surface them from the event log / `app.render()`, then:
research.submit_answer(f"{research_id}-q0", "yes, that is the goal")
# …answer each question; research drafts a spec artifact (unsigned).

# 2. Sign‑off gate — review the drafted spec body, then sign (or reject).
signoff = app.signoff(operator=ME)
spec = signoff.review(spec_id)             # dict: problem, scope, non_goals, interfaces, success_criteria, …
spec_id = signoff.sign(spec_id)            # passes the operator sign‑off gate
# signoff.reject(spec_id, "scope is wrong") to bounce it instead.

# 3. Director — decompose the SIGNED spec into an ordered, dependency-linked task plan.
plan_id = app.director().plan(CID, spec_id=spec_id)        # uses mcp-reasoning by default

# 4. Developer — write each task under the single-writer lock, in order.
dev = app.developer()
outcome = dev.dispatch(CID, task_id="myproj-t0")           # returns the task's TerminalOutcome
# A spec-claim deviation auto-retries (bounded, non-terminal) so the worker self-corrects.

# 5. Reviewer certification + integration (done earned twice; Invariant 5).
review = app.review()
certified = review.certify("myproj-t0")                    # fresh-context re-verify -> bool
if certified:
    review.integrate("myproj-t0")
```

Repeat steps 4–5 for each task in dependency order. Watch progress at any point with `app.render()`
(or `--follow`), or read `app.loop_state().tasks_by_state`.

## Loop decisions

The discrete decisions the autonomous agent used to make are now yours:

```python
td = app.task_decision(operator=ME)
td.list_pending(queue="all")               # planned/redundant tasks awaiting a decision
td.accept("…", row_id)
td.reject("…", row_id, "redundant with t3")

retro = app.retro(operator=ME)
retro.list_pending()                       # retro CANDIDATEs (antibodies / gate-changes) at operator review
retro.approve("antibody", row_id)          # or retro.reject(queue, row_id, reason)

prune = app.prune(operator=ME)
prune.list_expired()                       # expired trust grants (§S6)
prune.prune("quarterly cleanup")           # the operator-authorized delete

gc = app.enact_gate_change(operator=ME)
gc.list_approved()
gc.enact(row_id)                           # enact an approved gate change (Inv 12 still refuses core-gate weakening)
```

## The OSS path

```python
oss = app.oss(maintainer_verifier=…, license_fetcher=…)
oss.run(CID, envelope=…)   # intake hardening → four §S5 gates → fork-branch worktree → in-lock verifier
                           # → bot-identity commit → publish/PR, preserving the §S5 identity split
```

The OSS path is **operator‑only by decision** (2026‑07‑02): external intake — strangers requesting
contributions — is out of scope; every OSS run is you driving it against a repo you chose.

## Guarantees you can rely on

- Every action you take is recorded as an event through `EventBus.emit_sync`; there is no direct‑write
  code path in the console (a structural test, `test_console_source_has_no_direct_write_sql`, enforces
  it — it matches real `INSERT INTO` / `DELETE FROM` / `UPDATE … SET` statements, not the word in prose).
- Console‑surfaced state derives from the **same** projections and SSE stream the dashboard consumes —
  no parallel or divergent telemetry.
- The sign‑off gate, single‑writer lock, role boundaries, and earned‑twice completion fire identically
  to a driver‑driven run; driving from the console does not relax any of the 18 invariants.

## Notes

- **Same operations as the drivers.** Anything the console does, the `scripts/run_*.py` drivers and the
  `devharness` CLIs also do — the console is the operator‑facing wrapper, so you can mix the two.
- **`DEVHARNESS_DB`** selects the event store; one store per project (one correlation id per project).
- **Tests / CI:** the console's tests live in `tests/runtime/test_console_*.py` and run in the CI matrix.
- **Where it came from:** built end‑to‑end through the harness's own loop; the three harness defects the
  build surfaced (non‑goals structured‑verdict, scaffold‑test precision, the spec‑claim retry made
  non‑terminal) are fixed and committed. See `CLAUDE.md` for the full record.
