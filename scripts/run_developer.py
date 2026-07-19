"""Drive the live developer write step for the specledger scaffold task.

Loads the signed spec + drafted plan, then dispatches the plan's task through the
real DirectorRole.dispatch -> DeveloperRole loop: the developer takes the single
write lock, creates an isolated worktree (detached at HEAD, outside the repo),
takes a baseline checkpoint, and spawns a LIVE Agent SDK coding worker (no
write_hook, real sdk.query) whose only write surface is the scope-bounded
devharness-aci editor. We then run verifier-first acceptance (test_suite against
the worktree; failure auto-rewinds + rejects) and a fresh-context ReviewerRole
certification, and complete() the lifecycle only when BOTH pass (done earned
twice, Inv 5). integrate() decides the plan disposition (it does not git-merge —
the worktree is a sandbox).

Reviewer scope decision: the default reviewer verifier set
[parallax_verify, parallax_check, parallax_grounded_verify, test_suite] assumes a
structured claim + verbatim sources that a scaffold cert does not populate
(parallax_check is for computable claims; grounded_verify needs named sources). So
the reviewer is scoped to a fresh-context test_suite re-run — a real, independent
re-verification appropriate to a scaffold. (Finding: the reviewer default set is
unsuited to new_project_scaffold.)

Run:  python scripts/run_developer.py  (a stray ANTHROPIC_API_KEY is cleared at startup)
"""

import asyncio
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime"))

# The target repo the developer writes into. Defaults to devharness itself (the only case validated before
# external targeting); set DEVHARNESS_TARGET_REPO to build a feature in any external repo (e.g. pgharness).
# REPO stays the runtime-import + DB-default root; TARGET is the worktree/write target. Mirrors run_oss.py's
# DEVHARNESS_OSS_UPSTREAM_PATH -> base_path=upstream.
TARGET = Path(os.environ.get("DEVHARNESS_TARGET_REPO") or REPO)

import msgspec  # noqa: E402

from devharness import boot  # noqa: E402
from devharness.mcp.config import MCPConfigError, server_cfg  # noqa: E402
from devharness.artifacts.plan import PlanArtifact  # noqa: E402
from devharness.events.registry import TerminalOutcome  # noqa: E402
from devharness.health import emit_snapshot, leak_warning  # noqa: E402
from devharness.cli._bus import projected_bus  # noqa: E402
from devharness.mcp.mcp_reasoning import MCPReasoningClient  # noqa: E402
from devharness.mcp.parallax import ParallaxClient  # noqa: E402
from devharness.migrate import migrate  # noqa: E402
from devharness.console.developer import emit_client_costs, scratch_commit_subject  # noqa: E402
from devharness.roles.developer import DeveloperRole  # noqa: E402
from devharness.roles.director import DirectorRole  # noqa: E402
from devharness.roles.integration import integrate  # noqa: E402
from devharness.roles.reviewer import ReviewerRole  # noqa: E402
from devharness.models import model_for_tier  # noqa: E402
from devharness.task_classes.registry import TASK_CLASSES  # noqa: E402
from devharness.roles.scope_resolver import resolve_extra_scope  # noqa: E402
from devharness.sandbox.registry import resolve_launcher  # noqa: E402
from devharness.task_lifecycle.base import TaskLifecycle  # noqa: E402
from devharness.task_lifecycle.done_is_earned import complete, reject  # noqa: E402
import devharness.verifier.builtin  # noqa: E402,F401 — registers the builtin verifiers (test_suite, …)
from devharness.verifier.base import VerifierOk  # noqa: E402
from devharness.verifier.class_commands import derive_bump_fields, derive_regression_test_ref, language_for_test_command, pass_fail_command, regression_command  # noqa: E402
from devharness.verifier.runner import run_verifier  # noqa: E402
from devharness.worktree.contamination import foreign_scratch_correlations  # noqa: E402
from devharness.worktree.hygiene import purge_bytecode_caches  # noqa: E402

CORRELATION_ID = os.environ.get("DEVHARNESS_CORRELATION_ID", "specledger")
# The verifier's test target — the project's own test dir. Configurable so the driver isn't pinned to
# specledger (else jqlite's verifier would run specledger's tests in the worktree and falsely pass).
TEST_TARGET = os.environ.get("DEVHARNESS_TEST_TARGET", "tests/specledger")


def _sandbox_launcher():
    """Opt-in §S5 sandbox routing (#1a / C6): the ACI shell + test-runner route through a
    SandboxLauncher only when the operator sets DEVHARNESS_SANDBOX_PREFERRED (mock/wsl/vps); otherwise
    None = host. The mock launcher is fail-closed (its exec never runs the command), so it must NEVER be
    the silent default — that would deny every command. This wires the routing into the live driver
    (it was dormant: no driver ever set sandbox_launcher); the real WSL/VPS run stays operator-driven."""
    pref = os.environ.get("DEVHARNESS_SANDBOX_PREFERRED")
    return resolve_launcher(pref) if pref else None
# DEVHARNESS_TEST_MARKERS (Gap A′): a pytest -m expression to deselect tests the verifier can't run in a
# bare worktree — e.g. an external target's service-dependent tests ("not integration and not
# requires_postgres"). Unset = no filter (devharness-internal runs unchanged).
TEST_MARKERS = os.environ.get("DEVHARNESS_TEST_MARKERS")
# DEVHARNESS_TEST_COMMAND: a full verification command override (shell-split), run in the worktree root, for a
# target whose tests are not pytest — e.g. "cargo test --manifest-path sidecar/Cargo.toml" for a Rust change.
# When set it replaces the pytest command for every class's verifier (test_suite / bugfix / refactor).
_TEST_OVERRIDE = os.environ.get("DEVHARNESS_TEST_COMMAND")
TEST_COMMAND = shlex.split(_TEST_OVERRIDE) if _TEST_OVERRIDE else (
    ["python", "-m", "pytest", TEST_TARGET, "-q"] + (["-m", TEST_MARKERS] if TEST_MARKERS else []))


def _server_cfg(name: str) -> dict:
    """A named MCP server's live launch spec (rev 0.4.25: via the single config source,
    honoring DEVHARNESS_MCP_CONFIG with the ~/.claude.json fallback; never embedded)."""
    try:
        return server_cfg(name)
    except MCPConfigError as exc:
        sys.exit(str(exc))


def _stub_reasoning() -> MCPReasoningClient:
    async def _q(*, prompt, options):  # dispatch() never reasons
        if False:
            yield None
    return MCPReasoningClient(query_fn=_q)


def _clean_stale_worktree(task_id: str) -> None:
    wt = TARGET.parent / ".devharness-worktrees" / TARGET.name / task_id
    if wt.exists():
        subprocess.run(["git", "-C", str(TARGET), "worktree", "remove", "--force", str(wt)],
                       capture_output=True, text=True)
        if wt.exists():
            shutil.rmtree(wt, ignore_errors=True)
        subprocess.run(["git", "-C", str(TARGET), "worktree", "prune"], capture_output=True, text=True)
    # External-target re-dispatch: also delete the scratch branch so a retry can re-create it. The worktree
    # removal alone leaves the branch, and `git worktree add -b <same branch>` then fails (exit 255). Harmless
    # on a first dispatch (no such branch yet). Only ever the CURRENT task's branch — never a completed task's.
    if TARGET != REPO:
        subprocess.run(["git", "-C", str(TARGET), "branch", "-D", f"devharness/{task_id}"],
                       capture_output=True, text=True)


def _prune_terminal_worktrees(conn) -> None:
    """Remove pool worktrees for tasks that already reached a terminal. The harness creates a worktree
    per task but cleans only the current task_id before dispatch, so completed/rejected worktrees
    accumulate (disk + git registration). Adoption of a completed worktree happens between runs
    (before the next dispatch), so pruning terminal'd worktrees keeps the pool bounded without
    discarding an un-adopted result."""
    pool = TARGET.parent / ".devharness-worktrees" / TARGET.name
    if not pool.is_dir():
        return
    terminal = {r[0] for r in conn.execute(
        "SELECT DISTINCT json_extract(payload, '$.task_id') FROM events WHERE event_type='terminal_outcome'")}
    for d in pool.iterdir():
        if d.is_dir() and d.name in terminal:
            subprocess.run(["git", "-C", str(TARGET), "worktree", "remove", "--force", str(d)],
                           capture_output=True, text=True)
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
    subprocess.run(["git", "-C", str(TARGET), "worktree", "prune"], capture_output=True, text=True)


def _scratch_commit_identity() -> tuple[str, str]:
    """The (name, email) for a non-OSS external-target scratch commit. DEVHARNESS_COMMIT_IDENTITY is a JSON
    {"name","email"}; otherwise a generic devharness-dev identity (parallel to the OSS bot identity)."""
    raw = os.environ.get("DEVHARNESS_COMMIT_IDENTITY", "")
    if raw:
        try:
            d = json.loads(raw)
            if d.get("name") and d.get("email"):
                return d["name"], d["email"]
        except json.JSONDecodeError:
            pass
    return "devharness-dev", "dev@devharness.local"


def _commit_scratch_branch(wt_path: str, message: str) -> str:
    """Stage + commit the worker's certified changes onto the worktree's scratch branch (external target).
    Called ONLY after reviewer certification, so the realized diff was non-empty at verify time. Returns
    the commit sha. Purges bytecode caches first (rev 0.3.58) — the verifier's pytest run regenerates
    them after the in-run purge, and `git add -A` in a gitignore-less target would ship them."""
    purge_bytecode_caches(wt_path)
    name, email = _scratch_commit_identity()
    subprocess.run(["git", "-C", wt_path, "add", "-A"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", wt_path, "-c", f"user.name={name}", "-c", f"user.email={email}",
                    "commit", "-m", message], check=True, capture_output=True, text=True)
    return subprocess.run(["git", "-C", wt_path, "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()


def _transitive_descendants(plan, task_id) -> set:
    """Every task_id that depends on task_id, directly or transitively, per the plan's declared
    dependency graph — plus task_id itself. Used to exclude invalid chaining candidates: a task
    must never base its worktree on something that depends on IT."""
    excluded = {task_id}
    changed = True
    while changed:
        changed = False
        for t in plan.tasks:
            if t.task_id not in excluded and set(t.dependencies) & excluded:
                excluded.add(t.task_id)
                changed = True
    return excluded


def _latest_completed_branch(conn, correlation_id, plan, *, task_id) -> str | None:
    """devharness/<task_id> of the most recently COMPLETED task in this correlation, by actual
    build order (event seq), among tasks that are NOT task_id itself and NOT a declared descendant
    of task_id (see _transitive_descendants) — so a re-driven upstream/scaffold task never chains
    onto a downstream task that depends on it, and no task ever chains onto its own prior
    (about-to-be-deleted) branch. None when no valid candidate has completed yet (the first/scaffold
    task keeps basing off the target's own HEAD, same as before)."""
    excluded = _transitive_descendants(plan, task_id)
    for (tid,) in conn.execute(
        "SELECT json_extract(payload, '$.task_id') FROM events "
        "WHERE event_type = 'terminal_outcome' AND correlation_id = ? "
        "AND json_extract(payload, '$.outcome') = 'completed' "
        "ORDER BY seq DESC",
        (correlation_id,),
    ):
        if tid not in excluded:
            return f"devharness/{tid}"
    return None


def _self_correctable_rejection(conn, task_id) -> bool:
    """True iff the latest verifier_outcome for task_id failed on the spec_claim/parallax axis OR the
    test_coverage axis — both self-correctable (the worker can align the diff to the claim / add a test
    on retry). A cargo/test-suite failure, scope violation, spec_criteria violation, or infra crash is
    NOT this and is not auto-retried.
    NOTE: currently unreferenced — the actual retry gate is verifier/runner.py's own, separately-widened
    `retryable` check. Kept here, widened in parity, for any future caller."""
    latest = None
    for (payload,) in conn.execute("SELECT payload FROM events WHERE event_type='verifier_outcome'"):
        rec = json.loads(payload)
        if rec.get("task_id") == task_id:
            latest = rec
    detail = (latest.get("detail") or "") if latest else ""
    return bool(latest and latest.get("passed") is False and
                ("spec_claim axis" in detail or "test_coverage axis" in detail))


def main() -> int:
    # A stray ANTHROPIC_API_KEY kills the SDK subprocess at launch (exit 1); the harness bills
    # through the claude.ai login. Same posture as the console (tui.py) — rev 0.3.57.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    db_path = os.environ.get("DEVHARNESS_DB") or str(REPO / "var" / "devharness.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    migrate(conn)
    boot.run_boot_checks()  # #C4: fail closed at boot before any work
    bus = projected_bus(conn)

    # Contamination guard (rev 0.3.61): scratch branches whose correlation this store has never seen
    # mean TARGET was built by a different project's store (a wrong-target incident).
    # Warning-only — a deliberate re-target of an old repo into a fresh store is legitimate.
    foreign = foreign_scratch_correlations(conn, TARGET)
    if foreign:
        print(f"[run_developer] WARNING: {TARGET} carries devharness scratch branches from "
              f"correlation(s) this store has never seen: {', '.join(foreign)} — another project's "
              f"build target?")

    # rev 0.3.84: split the quality gate by tier — the first-pass verifier + non-goals check on the
    # cheaper T1 model, the fresh-context reviewer on frontier (one guaranteed-frontier pass of
    # done-earned-twice). Mirrors the console dispatch split.
    verifier_parallax = ParallaxClient(mcp_servers={"parallax": _server_cfg("parallax")},
                                       model=model_for_tier("T1"))  # #H6: claim verifiers (T1)
    reviewer_parallax = ParallaxClient(mcp_servers={"parallax": _server_cfg("parallax")})  # frontier

    spec_row = conn.execute(
        "SELECT artifact_id FROM artifacts WHERE artifact_type='spec' AND correlation_id=? AND signed=1 "
        "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1", (CORRELATION_ID,)).fetchone()
    if not spec_row:
        sys.exit("no signed spec — run + sign research first")
    spec_id = spec_row[0]

    plan_row = conn.execute(
        "SELECT artifact_id, payload_json FROM artifacts WHERE artifact_type='plan' AND correlation_id=? "
        "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1", (CORRELATION_ID,)).fetchone()
    if not plan_row:
        sys.exit("no plan — run run_director.py first")
    plan_id = plan_row[0]
    plan = msgspec.convert(json.loads(plan_row[1]), PlanArtifact)
    # Dispatch the next task that has not yet reached ANY terminal (plans are in topological order), so
    # repeated runs advance a multi-task plan. A task is SETTLED once it has a terminal_outcome of any kind
    # (completed / rejected / aborted); advance past it — never silently re-dispatch a rejected task (that
    # hung the build forever on a non-completable redundant task whose behaviour a prior task already
    # implemented). Re-driving a settled task is the explicit DEVHARNESS_TASK_ID override below; a rejected
    # task is surfaced for operator review, not auto-completed.
    terminal = {r[0] for r in conn.execute(
        "SELECT json_extract(payload, '$.task_id') FROM events WHERE event_type='terminal_outcome'").fetchall()}
    completed = {r[0] for r in conn.execute(
        "SELECT json_extract(payload, '$.task_id') FROM events WHERE event_type='terminal_outcome' "
        "AND json_extract(payload, '$.outcome')='completed'").fetchall()}
    pending = [t for t in plan.tasks if t.task_id not in terminal]
    # Operator affordance: DEVHARNESS_TASK_ID dispatches a SPECIFIC task, bypassing the first-pending
    # selection. Use to drive a task out of order or to advance past a non-completable (e.g. redundant)
    # rejected task that would otherwise be re-picked forever. Does not change the loop's verifier/retry
    # semantics — purely which task this run dispatches.
    override = os.environ.get("DEVHARNESS_TASK_ID")
    if override:
        task = next((t for t in plan.tasks if t.task_id == override), None)
        if task is None:
            sys.exit(f"DEVHARNESS_TASK_ID={override!r} is not in the {CORRELATION_ID} plan")
        print(f"[run_developer] task-id override -> dispatching {override}")
    else:
        if not pending:
            plan_ids = {t.task_id for t in plan.tasks}  # scope the counts to THIS plan (terminal/completed are global)
            n_done = len(plan_ids & completed)
            rejected = len(plan_ids & terminal) - n_done
            note = f" ({n_done} completed, {rejected} rejected/aborted — review the rejected)" if rejected else ""
            print(f"[run_developer] all {len(plan.tasks)} task(s) settled for {CORRELATION_ID}{note}")
            return 0
        # A mid-plan rejection/abort with pending siblings still gets silently skipped by the
        # pending[0] pick below (intentional, rev 0.3.37) — print a note so this run's operator
        # sees it was skipped, not just the all-settled case above.
        blocked_ahead = [t for t in plan.tasks if t.task_id in (terminal - completed)]
        if blocked_ahead:
            b = blocked_ahead[0]
            print(f"[run_developer] note: {b.task_id} is unresolved (rejected/aborted) — "
                  f"dispatching next pending task anyway; DEVHARNESS_TASK_ID={b.task_id} to retry it")
        task = pending[0]

    _clean_stale_worktree(task.task_id)
    _prune_terminal_worktrees(conn)  # bound the pool: discard worktrees of already-terminal tasks

    # Resource telemetry (per task): capture OS-resource state so process/worktree/memory growth is
    # visible on the dashboard, and warn pre-flight if the fsmonitor leak is recurring.
    snap = emit_snapshot(bus, CORRELATION_ID, base_path=str(TARGET))
    print(f"[run_developer] resources: {snap['process_count']} procs · {snap['git_process_count']} git · "
          f"{snap['worktree_count']} worktrees · {snap['free_memory_mb']}MB free")
    if (warn := leak_warning(snap)):
        print(f"[run_developer] ⚠ {warn}")

    # External-target write (Gap B): when building into a repo other than devharness itself, the developer
    # lands the feature on a named scratch branch in TARGET (never its main). None for a devharness-internal
    # run, which stays the detached/discard-after-run path (unchanged). Branch is unique per task to avoid a
    # `git worktree add -b` collision across a multi-task plan or a re-drive.
    scratch_branch = None
    if TARGET != REPO:
        scratch_branch = os.environ.get("DEVHARNESS_SCRATCH_BRANCH") or f"devharness/{task.task_id}"
    # Multi-task chaining (external builds): a task builds ON whichever sibling was actually completed
    # most recently in this correlation (real build order), not on its declared `dependencies` — so every
    # task's worktree already contains every previously-built sibling's work regardless of the plan's
    # dependency-graph shape (a fan-out plan's tasks would otherwise never see each other's edits, and
    # could conflict at assemble time). isolate cuts `-b <scratch> <base_ref>`.
    base_ref = None
    if scratch_branch is not None:
        base_ref = _latest_completed_branch(conn, CORRELATION_ID, plan, task_id=task.task_id)

    lifecycle = TaskLifecycle()
    # the bounded spec-claim auto-retry loop sets this before each dispatch; complete_task reads it so the
    # FINAL attempt's verifier failure is terminal while earlier attempts rewind non-terminally (Option 1).
    _attempt_ctl = {"final": True}

    async def complete_task(planned_task, developer, conn, event_bus):
        tid, cid = planned_task.task_id, planned_task.correlation_id
        wt = developer.worktree
        # #H6: dispatch the per-class verifier the director attached (verifier_ref), not a hardcoded
        # one; new_project_scaffold carries none, so it falls back to test_suite. The context carries
        # every field the per-class verifiers read (claim / regression / bump descriptors + parallax).
        verifier_name = planned_task.verifier_ref or "test_suite"
        # thread the spec's enumerated success-criteria into the verifier context so feature_spec_claim's
        # spec-anchored axis can check the realized diff doesn't VIOLATE one the task never tested (t7 fix)
        _spec_row = conn.execute("SELECT payload_json FROM artifacts WHERE artifact_id = ?", (spec_id,)).fetchone()
        spec_criteria = (json.loads(_spec_row[0]).get("success_criteria") or []) if _spec_row else []
        # the whole-product spec-criteria axis (feature_spec_claim) enforces only on the FINAL task — when
        # every OTHER plan task is already TERMINAL (completed or rejected), so the plan has settled.
        # Intermediate tasks skip it: a criterion a later task satisfies is incremental incompleteness, not
        # a violation. Gating on 'terminal' (not 'completed') means a redundant rejected task doesn't block
        # the final check forever. NOTE (honest scope): the axis reads the realized DIFF against HEAD — the
        # prior tasks are in that base only because the operator ADOPTS each completed worktree into HEAD
        # between runs (the integration step; `integrate()` does not git-merge). So this judges the final
        # diff against the assembled product under that adoption; it is NOT a whole-product completeness
        # check (a criterion no task implemented). A single-task plan is its own final task.
        # the outer `terminal` is rebound to None before this closure runs (:373); compute the set of
        # already-terminal task_ids locally so a multi-task plan's is_final_task check is correct.
        terminal_ids = {r[0] for r in conn.execute(
            "SELECT json_extract(payload, '$.task_id') FROM events WHERE event_type='terminal_outcome'")}
        is_final_task = not [t for t in plan.tasks if t.task_id != tid and t.task_id not in terminal_ids]
        vctx = {
            "task_id": tid, "correlation_id": cid, "cwd": wt.path, "test_command": TEST_COMMAND,
            "parallax": verifier_parallax,
            "diff_content": developer._realized_diff(wt),  # #C0: verify the realized change, not the proposal
            "spec_claim": planned_task.spec_claim or planned_task.description,
            "claim": planned_task.spec_claim or planned_task.description,
            "spec_success_criteria": spec_criteria,  # t7 fix: the spec-anchored axis reads these
            "is_final_task": is_final_task,  # whole-product axis enforces only when the product is complete
            "regression_test_ref": planned_task.regression_test_ref,
            "dependency_name": planned_task.dependency_name, "target_version": planned_task.target_version,
            "bump_command": planned_task.bump_command, "manifest_path": planned_task.manifest_path,
            "lockfile_path": planned_task.lockfile_path,
            "checkpoint": developer.checkpoint,
        }
        # #C0f: build the commands bugfix/refactor verifiers run from the task's fields — nothing did,
        # so those two classes could not run the live loop even though their verifier logic is correct.
        if _TEST_OVERRIDE:
            # the override IS the verification command for every class (e.g. cargo test for a Rust change)
            vctx["regression_command"] = TEST_COMMAND
            vctx["pass_fail_command"] = TEST_COMMAND
        else:
            # language-dispatched on the operator's test command (rev 0.4.9, console parity)
            lang = language_for_test_command(TEST_COMMAND)
            if verifier_name == "bugfix_regression":
                # rev 0.3.73: derive an empty regression_test_ref from the realized diff (explicit wins)
                ref = planned_task.regression_test_ref or derive_regression_test_ref(
                    vctx["diff_content"], lang)
                if ref:
                    vctx["regression_command"] = regression_command(ref, language=lang)
            if verifier_name == "refactor_behavior_preserving":
                vctx["pass_fail_command"] = pass_fail_command(TEST_TARGET, language=lang)
        if verifier_name == "dependency_resolves":
            # rev 0.3.70: a director-planned bump carries empty class fields — derive from the
            # realized diff, filling ONLY empties (explicit task fields win). Outside the
            # _TEST_OVERRIDE branch: the override replaces commands, not the class fields.
            for k, v in derive_bump_fields(vctx["diff_content"], wt.path).items():
                if not vctx.get(k):
                    vctx[k] = v
        lifecycle.transition(tid, "queued", "running", event_bus, conn)
        # verifier-first acceptance: failure auto-rewinds (clean) + rejects + emits the terminal
        result = await run_verifier(verifier_name, vctx, event_bus, conn,
                                    lifecycle=lifecycle, checkpoint=developer.checkpoint,
                                    terminal_on_fail=_attempt_ctl["final"])
        if not isinstance(result, VerifierOk):
            print(f"[run_developer] verifier ({verifier_name}) FAILED -> auto-rewind + rejected: {result.reason}")
            return
        # fresh-context reviewer cert: re-run the SAME acceptance verifier independently (done earned twice)
        reviewer = ReviewerRole(parallax=reviewer_parallax, event_bus=event_bus, conn=conn,
                                context=dict(vctx, prior_events=[]), fresh_context=True, verifiers=[verifier_name])
        certified = await reviewer.run(tid, spec_id, plan_id, cid)
        if certified:
            complete(tid, lifecycle, conn, event_bus)
            print(f"[run_developer] reviewer CERTIFIED ({verifier_name}) -> completed (done earned twice)")
            # Gap B: commit the certified change onto the scratch branch in the external target — AFTER
            # certification, so the realized diff the verifier read was non-empty (committing earlier empties
            # `git diff HEAD`). Devharness-internal runs (scratch_branch=None) keep the detached/no-commit path.
            if scratch_branch is not None:
                sha = _commit_scratch_branch(wt.path, scratch_commit_subject(planned_task))
                print(f"[run_developer] committed to scratch branch {scratch_branch} @ {sha[:10]} in {TARGET.name}")
        else:
            reject(tid, "reviewer rejected", lifecycle, conn, event_bus)
            print("[run_developer] reviewer REJECTED")

    director = DirectorRole.spawn(conn=conn, correlation_id=CORRELATION_ID,
                                  reasoning=_stub_reasoning(), event_bus=bus)
    # wire the non-goals guard's SEMANTIC conformance check to real parallax (#3): a task pursuing a spec
    # non-goal is denied at dispatch by parallax review, not just the conservative keyword heuristic
    director._non_goals_parallax = verifier_parallax

    print(f"[run_developer] db   = {db_path}")
    print(f"[run_developer] spec = {spec_id}  plan = {plan_id}")
    print(f"[run_developer] dispatching {task.task_id} [{task.task_class}] scope={task.scope_boundary}")
    print("[run_developer] spawning the LIVE coding worker — writes into an isolated worktree…")

    # Dispatch-time scope widening: union the model's scope with the files the change must ALSO touch (read from
    # the worktree, where a dependency's files exist). External, non-OSS targets only — internal builds and the
    # §S5-tightened OSS scope are left alone. Widen-only: it can never box the worker.
    scope_widener = None
    if TARGET != REPO and not getattr(task, "is_oss", False):
        async def scope_widener(worktree_path, planned_task):  # noqa: E306
            widener_model = model_for_tier("T1")  # advisory read-only exploration (rev 0.3.82)

            def _sink(amount_usd):  # SC-6: the widener session's realized spend, task-scoped
                bus.emit_sync(
                    "cost_spent",
                    {"role": "scope_resolver", "amount_usd": amount_usd, "model": widener_model,
                     "task_id": planned_task.task_id,
                     "spent_at_millis": int(time.time() * 1000), "correlation_id": CORRELATION_ID},
                    correlation_id=CORRELATION_ID,
                )
            extra = await resolve_extra_scope(worktree_path, planned_task, cost_sink=_sink,
                                              model=widener_model)
            if extra:
                print(f"[run_developer] scope widened (+{len(extra)}): {extra}")
            return extra

    # Route the writer to the task class's tier (rev 0.3.84): bugfix/dependency_bump (T1) write cheaper.
    _class_spec = TASK_CLASSES.get(task.task_class)
    developer_kwargs = {
        "base_path": str(TARGET),
        "model": model_for_tier(_class_spec.tier_minimum if _class_spec else "T2"),
        "scratch_branch": scratch_branch,  # Gap B: external-target writes land on a named branch (None = internal/detached)
        "base_ref": base_ref,  # multi-task chaining: a dependent task's branch is cut off its dependency's branch
        "scope_widener": scope_widener,  # dispatch-time scope widening (external, non-OSS) — widen-only union
        "worker_test_command": TEST_COMMAND if _TEST_OVERRIDE else None,  # worker self-tests with the SAME command the verifier runs
        "sandbox_launcher": _sandbox_launcher(),  # #1a/C6: opt-in §S5 sandbox routing (host by default)
        "mcp_server_configs": {
            "parallax": _server_cfg("parallax"),
            "mcp-reasoning": _server_cfg("mcp-reasoning"),
        },
    }
    # Automatic bounded retry on a spec_claim deviation: the worker self-corrects from the prior refutation
    # (now fed into its prompt via DeveloperRole._prior_rejection), removing the manual sharpen + re-dispatch.
    # Only a spec_claim/parallax rejection retries — a cargo/test failure or scope violation does not.
    retries = int(os.environ.get("DEVHARNESS_SPEC_CLAIM_RETRIES", "2"))
    terminal = None
    for attempt in range(retries + 1):
        if attempt > 0:
            print(f"[run_developer] spec-claim rejection — auto-retry {attempt}/{retries} "
                  f"(worker gets the prior verifier refutation as feedback)")
            _clean_stale_worktree(task.task_id)
            _prune_terminal_worktrees(conn)
        _attempt_ctl["final"] = (attempt == retries)
        pre_seq = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]
        asyncio.run(director.dispatch(
            task, DeveloperRole, conn, bus, plan_id=plan_id,
            complete_task=complete_task, developer_kwargs=developer_kwargs,
        ))
        # the terminal_outcome (if any) emitted during THIS attempt — seq-scoped, so a stale terminal from
        # a prior run/attempt is ignored. Its absence means a retryable spec-claim rewind: loop and re-run.
        row = conn.execute(
            "SELECT payload FROM events WHERE event_type='terminal_outcome' AND seq > ? "
            "AND json_extract(payload, '$.task_id') = ? ORDER BY seq DESC LIMIT 1",
            (pre_seq, task.task_id)).fetchone()
        if row is not None:
            d = json.loads(row[0])
            terminal = TerminalOutcome(
                task_id=task.task_id, outcome=d["outcome"], detail=d.get("detail", ""),
                reason=d.get("reason", ""), correlation_id=d.get("correlation_id", ""),
                terminated_at_millis=d.get("terminated_at_millis", 0))
            break
    if terminal is None:
        raise RuntimeError(f"auto-retry exhausted with no terminal for {task.task_id} (unreachable: the "
                           "final attempt forces terminal_on_fail)")
    # §S9 per-role spend (rev 0.3.56): the driver-owned parallax clients' realized cost — verifier
    # axes + fresh-context reviewer + the non-goals check, across every retry attempt (mirrors the
    # console dispatch loop; the developer's worker session emits separately from DeveloperRole.run).
    # One emission per DISTINCT client, each with ITS model (rev 0.4.2).
    emit_client_costs(bus, [verifier_parallax, reviewer_parallax],
                      role="verify_review", correlation_id=CORRELATION_ID, task_id=task.task_id)
    disposition = integrate(plan_id, task.task_id, terminal, conn, bus)

    wt_path = TARGET.parent / ".devharness-worktrees" / TARGET.name / task.task_id
    print(f"\n[run_developer] terminal       : {terminal.outcome}  ({terminal.reason or terminal.detail or '-'})")
    print(f"[run_developer] plan disposition: {disposition}")
    print(f"[run_developer] worktree (sandbox, not merged): {wt_path}")
    return 0 if terminal.outcome == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
