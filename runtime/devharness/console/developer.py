"""Operator console developer action — dispatch the developer to write a task.

The operator drives the loop directly, with no LLM agent in the operator seat making the
*dispatch* decision: ``dispatch`` resolves the signed spec + drafted plan for a correlation,
selects the next task to build, and dispatches it through the real
``DirectorRole.dispatch`` -> ``DeveloperRole`` loop — issuing the SAME operations as the
``run_developer`` driver. The developer takes the single write lock, creates an isolated
worktree, takes a baseline checkpoint, runs the coding worker (the only write surface is the
scope-bounded devharness-aci editor), then verifier-first acceptance + a fresh-context
``ReviewerRole`` certification complete the task only when BOTH pass (``completed`` earned
twice, Invariant 5). ``integrate`` decides the plan disposition.

Invariant 1 (single writer) is preserved exactly: the console never writes code — it dispatches
the ``DeveloperRole``, which alone acquires the ``SingleWriterLock`` and writes inside its own
worktree. The developer scope boundary is preserved exactly: ``DeveloperRole`` enforces
``scope_boundary`` on the realized worktree diff and rewinds + flags any out-of-scope change, so
the director rejects it (the console adds no write path of its own). The console action is the
operator pressing "dispatch developer"; the director and developer remain the agents.

The loop's events (write_lock_acquired/released, task_started, write_applied, verifier_outcome,
reviewer_certified, terminal_outcome, director_decision) flow through the supplied ``EventBus``
``emit_sync`` — the console's sole sanctioned write path; it issues no event-store or projection
write directly. Spec / plan resolution is SELECT-only.
"""

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import msgspec

from devharness.artifacts.plan import PlanArtifact
from devharness.console.director import NoSignedSpec
from devharness.events.registry import TerminalOutcome
from devharness.health import emit_snapshot
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.mcp.base import TRANSIENT_SDK_RESULT
from devharness.mcp.parallax import ParallaxClient
from devharness.monitor.sweep import run_invariant_sweep
from devharness.models import model_for_tier
from devharness.roles.developer import DeveloperRole
from devharness.roles.director import DirectorRole
from devharness.roles.integration import integrate
from devharness.roles.reviewer import ReviewerRole
from devharness.task_classes.registry import TASK_CLASSES
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.task_lifecycle.done_is_earned import abort, complete, reject
import devharness.verifier.builtin  # noqa: F401  (registers the builtin per-class verifiers)
from devharness.verifier.base import VerifierOk
from devharness.verifier.class_commands import derive_bump_fields, derive_regression_test_ref, language_for_test_command, pass_fail_command, regression_command
from devharness.worktree.hygiene import purge_bytecode_caches

# The devharness repo root (this file is at runtime/devharness/console/developer.py). A build whose
# base_path is NOT this repo is an "external target": its certified change lands on a per-task scratch
# branch (mirrors run_developer), not detached-and-discarded as an internal devharness build is.
_DEVHARNESS_REPO = Path(__file__).resolve().parents[3]


def _scratch_commit_identity() -> tuple[str, str]:
    """The (name, email) for an external-target scratch commit (parallel to run_developer)."""
    raw = os.environ.get("DEVHARNESS_COMMIT_IDENTITY", "")
    if raw:
        try:
            d = json.loads(raw)
            if d.get("name") and d.get("email"):
                return d["name"], d["email"]
        except json.JSONDecodeError:
            pass
    return "devharness-dev", "dev@devharness.local"


def emit_client_costs(writer, clients, *, role, correlation_id, task_id="", now_millis=None):
    """One ``cost_spent`` per DISTINCT client that spent — each carries ITS model (rev 0.4.2: the
    verify_review sum hid the T1-verifier/frontier-reviewer split, so tier routing was invisible in
    the ledger). Identity-deduped (tests inject one client for both seats -> one emission); zero-cost
    clients emit nothing. Shared by the console dispatch/OSS loops, the certify action, and the
    scripts/run_* drivers (the scratch_commit_subject precedent — no re-hardcoded sums)."""
    now = now_millis or (lambda: int(time.time() * 1000))
    seen = []
    for client in clients:
        if client is None or any(client is s for s in seen):
            continue
        seen.append(client)
        spent = float(getattr(client, "total_cost_usd", 0) or 0)
        if not spent > 0:  # matches the old sites' `if spent > 0` polarity — also skips NaN
            continue
        payload = {"role": role, "amount_usd": spent, "model": getattr(client, "model", "") or "",
                   "spent_at_millis": now(), "correlation_id": correlation_id}
        if task_id:
            payload["task_id"] = task_id
        writer.emit_sync("cost_spent", payload, correlation_id=correlation_id)


def scratch_commit_subject(planned_task) -> str:
    """Commit subject for a certified external-target change — carries the task's REAL class.
    The subject was hardcoded 'feature', so every bugfix/refactor/dependency_bump landed git-labeled
    as a feature (a prior drive surfaced it); the event log always had the true class, this makes
    the git provenance trail agree. Shared with scripts/run_developer.py (the rev-0.3.71 parity pair)."""
    cls = getattr(planned_task, "task_class", "") or "task"
    return f"devharness {cls} {planned_task.task_id}: {planned_task.description[:60]}"


def _commit_scratch_branch(wt_path: str, message: str) -> str:
    """Stage + commit the certified change onto the worktree's scratch branch (external target).
    Called ONLY after reviewer certification, so the realized diff was non-empty at verify time.
    Purges bytecode caches first (rev 0.3.58) — the verifier's pytest run regenerates them after the
    in-run purge, and `git add -A` in a gitignore-less target would ship them (a prior drive did)."""
    purge_bytecode_caches(wt_path)
    name, email = _scratch_commit_identity()
    subprocess.run(["git", "-C", wt_path, "add", "-A"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", wt_path, "-c", f"user.name={name}", "-c", f"user.email={email}",
                    "commit", "-m", message], check=True, capture_output=True, text=True)
    return subprocess.run(["git", "-C", wt_path, "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
from devharness.verifier.runner import run_verifier


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


class NoPlan(RuntimeError):
    """Raised when the operator dispatches the developer with no drafted plan to build."""


class UnknownTask(RuntimeError):
    """Raised when an explicit task_id is not present in the resolved plan."""


class AllTasksSettled(RuntimeError):
    """Raised when every plan task has already reached a terminal (nothing left to dispatch)."""


def _server_cfg(name: str) -> dict:
    """Read a named MCP server's live launch spec from ~/.claude.json (never embed it).

    Mirrors ``run_developer``'s ``_server_cfg`` / ``ConsoleDirector``'s reader: the launch spec
    is operator-local and machine-specific, so it is read live, never committed.
    """
    path = Path.home() / ".claude.json"
    if not path.exists():
        raise RuntimeError(f"no {path} — cannot find the {name} MCP server launch spec")
    server = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {}).get(name)
    if not server:
        raise RuntimeError(f"{name} not found under mcpServers in ~/.claude.json")
    return server


def live_parallax_client(model=None) -> ParallaxClient:
    """The live parallax client, built from ~/.claude.json.

    Mirrors ``run_developer``'s ``verifier_parallax``. ``model`` routes the client to a cost tier
    (rev 0.3.82): the verifier + fresh-context reviewer pass nothing and keep the frontier default
    (the done-earned-twice quality gate stays strong); the research interview passes the T1 advisory
    model. ``None`` -> ``default_model()`` via ``MCPClient``.
    """
    return ParallaxClient(mcp_servers={"parallax": _server_cfg("parallax")}, model=model)


def _stub_reasoning() -> MCPReasoningClient:
    """A no-op mcp-reasoning client: ``DirectorRole.dispatch`` never reasons (it plans nothing;
    the plan already exists), so the dispatch path needs no live reasoning client."""

    async def _q(*, prompt, options):
        if False:
            yield None

    return MCPReasoningClient(query_fn=_q)


class ConsoleDeveloper:
    """Operator-driven developer dispatch: write one plan task via the real DirectorRole/DeveloperRole.

    Constructed against the console connection and its ``EventBus`` writer (the emit-only write
    path). ``dispatch`` resolves the signed spec + plan, selects the task, and dispatches it —
    the same operations as the ``run_developer`` driver. The ``DeveloperRole`` alone holds the
    single write lock and writes inside its isolated worktree (Invariant 1), scope-bounded on its
    realized diff; the console adds no write path of its own.
    """

    def __init__(self, conn, writer, *, base_path=None, test_target=None, test_command=None,
                 now_millis=None):
        self._conn = conn
        self._writer = writer  # an EventBus — emit_sync is the only sanctioned write path
        # The repo the developer writes into; defaults to the harness checkout root (the
        # validated devharness-internal target). Mirrors run_developer's DEVHARNESS_TARGET_REPO.
        # Default to the absolute devharness repo (not "." — which resolves against CWD, so launching
        # from a subdir would mis-detect an internal build as external).
        self._base_path = Path(base_path or os.environ.get("DEVHARNESS_TARGET_REPO") or str(_DEVHARNESS_REPO))
        # The verifier's test target (the project's own test dir) — refactor's pass/fail command reads it.
        self._test_target = test_target or os.environ.get("DEVHARNESS_TEST_TARGET", "tests")
        # The acceptance test command the verifier runs against the worktree.
        self._test_command = test_command or ["python", "-m", "pytest", self._test_target, "-q"]
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))

    def spawn_director(self, correlation_id, *, reasoning=None) -> DirectorRole:
        """Spawn the DirectorRole that performs the dispatch — read/plan only, no write tools.

        ``run_developer`` spawns the director the same way; dispatch is the only way the director
        touches code, and only through the developer subprocess (Invariant 3 holds — dispatch is
        not a write).
        """
        return DirectorRole.spawn(
            conn=self._conn,
            correlation_id=correlation_id,
            reasoning=reasoning or _stub_reasoning(),
            event_bus=self._writer,
            now_millis=self._now_millis,
        )

    def dispatch(self, correlation_id, *, task_id=None, spec_id=None, plan_id=None,
                 reasoning=None, parallax=None, developer_kwargs=None, lifecycle=None,
                 spec_claim_retries=2, snapshot=True):
        """Dispatch the developer to write one plan task; return its ``TerminalOutcome``.

        Resolves the most recent operator-signed spec and the most recent plan for
        ``correlation_id`` (explicit ``spec_id`` / ``plan_id`` override resolution), selects the
        next task that has not reached a terminal (an explicit ``task_id`` dispatches that task
        out of order, advancing past a settled one), then runs the same operations as the
        ``run_developer`` driver: clean the stale worktree, dispatch via ``DirectorRole.dispatch``
        -> ``DeveloperRole`` (single write lock, isolated worktree, scope-bounded realized diff),
        verifier-first acceptance + fresh-context reviewer certification (``completed`` earned
        twice, Invariant 5), and ``integrate`` the terminal. Re-dispatches up to
        ``spec_claim_retries`` times on a spec-claim deviation (the worker self-corrects from the
        prior refutation), exactly like ``run_developer``.

        Raises ``NoSignedSpec`` when no signed spec exists, ``NoPlan`` when no plan exists,
        ``UnknownTask`` for an unknown ``task_id``, and ``AllTasksSettled`` when every task is
        already terminal.
        """
        spec_id = spec_id or self._latest_signed_spec(correlation_id)
        if spec_id is None:
            raise NoSignedSpec(
                f"no signed spec for correlation_id {correlation_id!r} — run + sign research first"
            )
        plan_id, plan = self._resolve_plan(correlation_id, plan_id)
        task = self._select_task(plan, task_id)

        # Split the quality gate by tier (rev 0.3.84): the first-pass verifier + the dispatch-time
        # non-goals check are the high-volume advisory traffic, routed to the cheaper T1 model; the
        # fresh-context reviewer keeps the frontier model, so "done earned twice" always retains ONE
        # frontier pass. An injected parallax (tests) serves both — the split is live-only.
        if parallax is not None:
            verifier_parallax = reviewer_parallax = parallax
        else:
            verifier_parallax = live_parallax_client(model=model_for_tier("T1"))
            reviewer_parallax = live_parallax_client()
        lifecycle = lifecycle or TaskLifecycle()
        dev_kwargs = developer_kwargs if developer_kwargs is not None else self._default_developer_kwargs()
        # External-target write (base_path is not the devharness repo): land the certified change on a
        # per-task scratch branch, and chain a dependent task onto its dependency's branch so a multi-task
        # plan accumulates (mirrors run_developer). Internal devharness builds keep the detached path.
        scratch_branch = None
        if developer_kwargs is None:
            ext = self._external_target_kwargs(task, plan)
            if ext:
                dev_kwargs = dict(dev_kwargs, **ext)
                scratch_branch = ext["scratch_branch"]
                if not getattr(task, "is_oss", False):
                    # Dispatch-time scope widening (rev 0.3.71, run_developer parity): union the
                    # model's scope with the files the change must ALSO touch, read from the real
                    # worktree. Widen-only. The gap bit live: a bump scoped to dependency metadata
                    # could never update the repo's own version-pin test, so the suite axis
                    # rejected every retry — structurally uncompletable. Guarded by the
                    # developer_kwargs-is-None gate, so tests with stubbed kwargs never spawn SDK.
                    dev_kwargs["scope_widener"] = self._make_scope_widener(task.correlation_id)
            # Route the WRITER to the task class's tier (rev 0.3.84): bugfix/dependency_bump (T1)
            # write on the cheaper model; the other build classes (T2) stay frontier. Live-only.
            _class_spec = TASK_CLASSES.get(task.task_class)
            dev_kwargs["model"] = model_for_tier(_class_spec.tier_minimum if _class_spec else "T2")

        director = self.spawn_director(correlation_id, reasoning=reasoning)
        # Wire the non-goals guard's SEMANTIC conformance check to real parallax (as run_developer
        # does): a task pursuing a signed-spec non-goal is denied at dispatch by parallax review,
        # not only the conservative keyword heuristic. Advisory pre-write check -> the T1 client.
        director._non_goals_parallax = verifier_parallax

        _attempt_ctl = {"final": True}
        complete_task = self._make_complete_task(
            spec_id, plan_id, plan, verifier_parallax, reviewer_parallax, lifecycle, scratch_branch, _attempt_ctl
        )

        self._clean_stale_worktree(task.task_id)
        self._prune_terminal_worktrees()
        if snapshot:
            emit_snapshot(self._writer, correlation_id, base_path=str(self._base_path))

        terminal = None
        crash = None
        for attempt in range(spec_claim_retries + 1):
            if attempt > 0:
                self._clean_stale_worktree(task.task_id)
                self._prune_terminal_worktrees()
            # non-final attempts rewind a spec-claim deviation NON-terminally (the reused lifecycle stays
            # non-terminal for the retry); the final attempt forces a terminal — mirrors run_developer.
            _attempt_ctl["final"] = (attempt == spec_claim_retries)
            pre_seq = self._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]
            try:
                asyncio.run(director.dispatch(
                    task, DeveloperRole, self._conn, self._writer,
                    plan_id=plan_id, complete_task=complete_task, developer_kwargs=dev_kwargs,
                ))
            except Exception as exc:  # noqa: BLE001
                # Retry the transient SDK 'error result: success' glitch (rev 0.3.86) — the next loop
                # iteration cleans the stale worktree and re-dispatches. Any other hard crash (git
                # identity, missing `python`, a real SDK error) is NOT retried as a spec-claim rewind;
                # force an aborted terminal below so it surfaces (Inv 10, no silent loop).
                if attempt < spec_claim_retries and TRANSIENT_SDK_RESULT in str(exc):
                    continue
                crash = exc
                break
            # the terminal_outcome emitted during THIS attempt (seq-scoped; a stale terminal from a prior
            # attempt/run is ignored). Its absence = a retryable spec-claim rewind: loop and re-run.
            row = self._conn.execute(
                "SELECT payload FROM events WHERE event_type='terminal_outcome' AND seq > ? "
                "AND json_extract(payload, '$.task_id') = ? ORDER BY seq DESC LIMIT 1",
                (pre_seq, task.task_id),
            ).fetchone()
            if row is not None:
                d = json.loads(row[0])
                terminal = TerminalOutcome(
                    task_id=task.task_id, outcome=d["outcome"], detail=d.get("detail", ""),
                    reason=d.get("reason", ""), correlation_id=d.get("correlation_id", ""),
                    terminated_at_millis=d.get("terminated_at_millis", 0),
                )
                break
        # §S9 per-role spend (rev 0.3.56): the dispatch-loop-owned parallax clients' realized cost —
        # verifier axes + fresh-context reviewer + the non-goals check, across every retry attempt of
        # this dispatch (the clients persist across attempts; the developer's own worker session emits
        # separately from DeveloperRole.run). One emission per DISTINCT client, each with ITS model
        # (rev 0.4.2 — the prior sum hid the T1/frontier split). Zero-cost (mocked) dispatches emit
        # nothing. Site is load-bearing: BEFORE the terminal-abort block below, so event order vs
        # terminal_outcome (retro preceding_events windows) is unchanged.
        emit_client_costs(self._writer, [verifier_parallax, reviewer_parallax],
                          role="verify_review", correlation_id=correlation_id, task_id=task.task_id)
        if terminal is None:
            # No terminal was emitted — either a mid-dispatch crash (``crash`` set) or retries
            # exhausted on a non-terminal spec-claim rewind. Force an ``aborted`` terminal so the task
            # reaches a terminal (Invariant 10: a started task emits exactly one) and the failure
            # SURFACES — the plan blocks and the ``→ next`` hint shows the explicit retry command —
            # instead of the task silently staying pending and the loop re-dispatching it forever
            # (the "looping on N" symptom the first real panel-driven build hit, rev 0.3.86).
            reason = (f"dispatch crashed: {type(crash).__name__}: {crash}" if crash is not None
                      else "dispatch produced no terminal after all retries")
            abort(task.task_id, reason, lifecycle, self._conn, self._writer)
            row = self._conn.execute(
                "SELECT payload FROM events WHERE event_type='terminal_outcome' "
                "AND json_extract(payload, '$.task_id') = ? ORDER BY seq DESC LIMIT 1",
                (task.task_id,),
            ).fetchone()
            d = json.loads(row[0])
            terminal = TerminalOutcome(
                task_id=task.task_id, outcome=d["outcome"], detail=d.get("detail", ""),
                reason=d.get("reason", ""), correlation_id=d.get("correlation_id", ""),
                terminated_at_millis=d.get("terminated_at_millis", 0),
            )
        integrate(plan_id, task.task_id, terminal, self._conn, self._writer)
        # Live invariant monitor (rev 0.3.87): sweep the log now that this task has settled (the lock is
        # released, so the Inv-10 orphan half can run) and emit invariant_violated for any new breach.
        # Advisory — a monitor error must never break a build.
        try:
            run_invariant_sweep(self._conn, self._writer)
        except Exception:  # noqa: BLE001
            pass
        return terminal

    # --- the inner accept loop (mirrors scripts/run_developer.py) ---

    def _make_complete_task(self, spec_id, plan_id, plan, verifier_parallax, reviewer_parallax,
                            lifecycle, scratch_branch, attempt_ctl):
        """Build the verifier-first-acceptance + fresh-context-reviewer closure run after the
        developer writes — the same shape ``run_developer`` builds (``completed`` earned twice). The
        verifier runs on ``verifier_parallax`` (T1) and the reviewer on ``reviewer_parallax``
        (frontier) — the same object when a parallax is injected (tests)."""

        async def complete_task(planned_task, developer, conn, event_bus):
            tid, cid = planned_task.task_id, planned_task.correlation_id
            wt = developer.worktree
            # dispatch the per-class verifier the director attached (verifier_ref), not a hardcoded
            # one; new_project_scaffold carries none, so it falls back to test_suite.
            verifier_name = planned_task.verifier_ref or "test_suite"
            srow = conn.execute(
                "SELECT payload_json FROM artifacts WHERE artifact_id = ?", (spec_id,)
            ).fetchone()
            spec_criteria = (json.loads(srow[0]).get("success_criteria") or []) if srow else []
            # the whole-product spec-criteria axis enforces only on the FINAL task — when every
            # OTHER plan task is already terminal; intermediate tasks skip it (incremental builds).
            terminal_ids = {
                r[0] for r in conn.execute(
                    "SELECT json_extract(payload, '$.task_id') FROM events "
                    "WHERE event_type='terminal_outcome'"
                )
            }
            is_final_task = not [
                t for t in plan.tasks if t.task_id != tid and t.task_id not in terminal_ids
            ]
            vctx = {
                "task_id": tid, "correlation_id": cid, "cwd": wt.path,
                "test_command": self._test_command,
                "parallax": verifier_parallax,  # rev 0.3.84: the first-pass verifier runs on T1
                "diff_content": developer._realized_diff(wt),  # verify the realized change, not the proposal
                "spec_claim": planned_task.spec_claim or planned_task.description,
                "claim": planned_task.spec_claim or planned_task.description,
                "spec_success_criteria": spec_criteria,
                "is_final_task": is_final_task,
                "regression_test_ref": planned_task.regression_test_ref,
                "dependency_name": planned_task.dependency_name,
                "target_version": planned_task.target_version,
                "bump_command": planned_task.bump_command,
                "manifest_path": planned_task.manifest_path,
                "lockfile_path": planned_task.lockfile_path,
                "checkpoint": developer.checkpoint,
            }
            # build the commands the bugfix/refactor verifiers run from the task's fields —
            # language-dispatched on the operator's test command (rev 0.4.9: cargo → the Rust
            # wrappers; the pytest-only builders made non-Python bugfix/refactor uncompletable).
            lang = language_for_test_command(self._test_command)
            if verifier_name == "bugfix_regression":
                # rev 0.3.73: a director-planned bugfix leaves regression_test_ref empty (it can't
                # know the test path before the worker writes it) — derive it from the realized diff.
                ref = planned_task.regression_test_ref or derive_regression_test_ref(
                    vctx["diff_content"], lang)
                if ref:
                    vctx["regression_command"] = regression_command(ref, language=lang)
                # else: no derivable single test file → the verifier fails closed naming the gap
            if verifier_name == "refactor_behavior_preserving":
                vctx["pass_fail_command"] = pass_fail_command(self._test_target, language=lang)
            if verifier_name == "dependency_resolves":
                # rev 0.3.70: a director-planned bump carries empty class fields (only the
                # operator-injected script flow ever set them) — derive from the realized diff,
                # filling ONLY empties so explicit task fields always win.
                for k, v in derive_bump_fields(vctx["diff_content"], wt.path).items():
                    if not vctx.get(k):
                        vctx[k] = v
            lifecycle.transition(tid, "queued", "running", event_bus, conn)
            # verifier-first acceptance: failure auto-rewinds (clean) + rejects + emits the terminal
            result = await run_verifier(
                verifier_name, vctx, event_bus, conn,
                lifecycle=lifecycle, checkpoint=developer.checkpoint,
                terminal_on_fail=attempt_ctl["final"],
            )
            if not isinstance(result, VerifierOk):
                return
            # fresh-context reviewer cert: re-run the SAME acceptance verifier independently, on the
            # FRONTIER client (rev 0.3.84) — the one guaranteed-frontier pass of "done earned twice".
            reviewer = ReviewerRole(
                parallax=reviewer_parallax, event_bus=event_bus, conn=conn,
                context=dict(vctx, prior_events=[]), fresh_context=True, verifiers=[verifier_name],
            )
            certified = await reviewer.run(tid, spec_id, plan_id, cid)
            if certified:
                complete(tid, lifecycle, conn, event_bus)
                # external target: commit the certified change onto its scratch branch AFTER cert (an
                # earlier commit would empty the realized diff the verifier read).
                if scratch_branch is not None:
                    _commit_scratch_branch(wt.path, scratch_commit_subject(planned_task))
            else:
                reject(tid, "reviewer rejected", lifecycle, conn, event_bus)

        return complete_task

    def _external_target_kwargs(self, task, plan) -> dict:
        """Scratch-branch + base_ref kwargs for an EXTERNAL-target build (empty for a devharness-internal
        build). External: the certified change lands on a per-task ``devharness/<task_id>`` branch, based
        on whichever task was actually completed most recently in this correlation (real build order) —
        not the declared ``dependencies`` field — so every task's worktree already contains every
        previously-built sibling's work regardless of the plan's dependency-graph shape (a fan-out plan's
        tasks would otherwise never see each other's edits, and could conflict at assemble time)."""
        if self._base_path.resolve() == _DEVHARNESS_REPO:
            return {}
        kwargs = {"scratch_branch": f"devharness/{task.task_id}"}
        base_ref = _latest_completed_branch(self._conn, task.correlation_id, plan, task_id=task.task_id)
        if base_ref is not None:
            kwargs["base_ref"] = base_ref
        return kwargs

    def _make_scope_widener(self, correlation_id):
        """The dispatch-time scope widener closure (external, non-OSS targets): a read-only SDK
        session over the worktree returns the extra files the change must also edit; its realized
        cost emits task-scoped (SC-6, role=scope_resolver). Mirrors scripts/run_developer.py."""
        from devharness.models import model_for_tier
        from devharness.roles.scope_resolver import resolve_extra_scope

        async def scope_widener(worktree_path, planned_task):
            # scope widening is advisory (read-only exploration) — route to the T1 model (rev 0.3.82)
            widener_model = model_for_tier("T1")

            def _sink(amount_usd):
                self._writer.emit_sync(
                    "cost_spent",
                    {"role": "scope_resolver", "amount_usd": amount_usd, "model": widener_model,
                     "task_id": planned_task.task_id,
                     "spent_at_millis": self._now_millis(),
                     "correlation_id": correlation_id},
                    correlation_id=correlation_id,
                )
            return await resolve_extra_scope(worktree_path, planned_task, cost_sink=_sink,
                                             model=widener_model)

        return scope_widener

    def _default_developer_kwargs(self) -> dict:
        """The live operator developer kwargs: write into ``base_path`` with advisory MCP servers
        wired from ~/.claude.json (the ACI server is always bound in-process by the developer)."""
        return {
            "base_path": str(self._base_path),
            "worker_test_command": self._test_command,  # worker self-tests with the verifier's command
            "mcp_server_configs": {
                "parallax": _server_cfg("parallax"),
                "mcp-reasoning": _server_cfg("mcp-reasoning"),
            },
        }

    # --- task selection ---

    def _select_task(self, plan, task_id):
        """With no explicit task_id, picks the first task with no terminal_outcome at all — this
        deliberately advances past ANY terminal (completed/rejected/aborted), mirroring
        scripts/run_developer.py (rev 0.3.37: refusing to advance past a non-completable rejected
        task hung the whole plan forever). It does NOT refuse when an earlier task is rejected/
        aborted — ConsoleTUI._next_hint() (tui.py) is the surface responsible for warning the
        operator BEFORE that happens; don't "fix" this into a refusal without preserving that
        warning, or the rev-0.3.37 hang comes back."""
        if task_id is not None:
            task = next((t for t in plan.tasks if t.task_id == task_id), None)
            if task is None:
                raise UnknownTask(f"task_id {task_id!r} is not in plan {plan.plan_id!r}")
            return task
        terminal = {
            r[0] for r in self._conn.execute(
                "SELECT json_extract(payload, '$.task_id') FROM events "
                "WHERE event_type='terminal_outcome'"
            )
        }
        pending = [t for t in plan.tasks if t.task_id not in terminal]
        if not pending:
            raise AllTasksSettled(
                f"all {len(plan.tasks)} task(s) in plan {plan.plan_id!r} have reached a terminal"
            )
        return pending[0]

    def _self_correctable_rejection(self, task_id) -> bool:
        """True iff the latest verifier_outcome for task_id failed on the spec_claim/parallax axis OR
        the test_coverage axis — both self-correctable. A test-suite failure, scope violation,
        spec_criteria violation, or infra crash is not.
        NOTE: currently unreferenced — the actual retry gate is verifier/runner.py's own, separately-
        widened `retryable` check. Kept here, widened in parity, for any future caller."""
        latest = None
        for (payload,) in self._conn.execute(
            "SELECT payload FROM events WHERE event_type='verifier_outcome'"
        ):
            rec = json.loads(payload)
            if rec.get("task_id") == task_id:
                latest = rec
        detail = (latest.get("detail") or "") if latest else ""
        return bool(
            latest and latest.get("passed") is False
            and ("spec_claim axis" in detail or "test_coverage axis" in detail)
        )

    # --- worktree hygiene (git subprocess; mirrors run_developer) ---

    def _clean_stale_worktree(self, task_id) -> None:
        target = self._base_path
        wt = target.parent / ".devharness-worktrees" / target.name / task_id
        if wt.exists():
            subprocess.run(
                ["git", "-C", str(target), "worktree", "remove", "--force", str(wt)],
                capture_output=True, text=True,
            )
            if wt.exists():
                shutil.rmtree(wt, ignore_errors=True)
            subprocess.run(
                ["git", "-C", str(target), "worktree", "prune"], capture_output=True, text=True
            )
        # External target: the scratch branch is created at worktree-add time (-b devharness/<id>), so a
        # retry / re-drive must delete it too — else `git worktree add -b <same>` fails ("branch exists").
        if target.resolve() != _DEVHARNESS_REPO:
            subprocess.run(
                ["git", "-C", str(target), "branch", "-D", f"devharness/{task_id}"],
                capture_output=True, text=True,
            )

    def _prune_terminal_worktrees(self) -> None:
        """Remove pool worktrees for tasks that already reached a terminal — bound the pool."""
        target = self._base_path
        pool = target.parent / ".devharness-worktrees" / target.name
        if not pool.is_dir():
            return
        terminal = {
            r[0] for r in self._conn.execute(
                "SELECT DISTINCT json_extract(payload, '$.task_id') FROM events "
                "WHERE event_type='terminal_outcome'"
            )
        }
        for d in pool.iterdir():
            if d.is_dir() and d.name in terminal:
                subprocess.run(
                    ["git", "-C", str(target), "worktree", "remove", "--force", str(d)],
                    capture_output=True, text=True,
                )
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
        subprocess.run(
            ["git", "-C", str(target), "worktree", "prune"], capture_output=True, text=True
        )

    # --- read-only lookups (SELECT-only; no event-store or projection writes) ---

    def _latest_signed_spec(self, correlation_id):
        row = self._conn.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE artifact_type = 'spec' AND correlation_id = ? AND signed = 1 "
            "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1",
            (correlation_id,),
        ).fetchone()
        return row[0] if row else None

    def _resolve_plan(self, correlation_id, plan_id):
        if plan_id is not None:
            row = self._conn.execute(
                "SELECT artifact_id, payload_json FROM artifacts "
                "WHERE artifact_id = ? AND artifact_type = 'plan'",
                (plan_id,),
            ).fetchone()
            if row is None:
                raise NoPlan(f"no plan artifact with id {plan_id!r}")
        else:
            row = self._conn.execute(
                "SELECT artifact_id, payload_json FROM artifacts "
                "WHERE artifact_type = 'plan' AND correlation_id = ? "
                "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1",
                (correlation_id,),
            ).fetchone()
            if row is None:
                raise NoPlan(
                    f"no plan for correlation_id {correlation_id!r} — dispatch the director first"
                )
        return row[0], msgspec.convert(json.loads(row[1]), PlanArtifact)
