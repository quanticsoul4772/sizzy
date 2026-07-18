"""Operator console OSS action — drive the §S5 OSS-contribution path end-to-end.

The operator drives the OSS loop directly, with no LLM agent in the operator seat making the
*dispatch* decision: ``run`` issues the SAME operations as the ``scripts/run_oss.py`` driver —

  1. **intake hardening** (``oss.intake.process_intake``): the §S5 front door runs fail-closed —
     requester cooldown → SPDX license allowlist → license verification against the upstream
     repo's real SPDX id → maintainer verification → context-injection scan. A reject records no
     intake (so the director's intake-required check refuses the task); only an all-clean request
     records ``oss_task_intake`` + ``intake_decision(accepted)``.
  2. on accept, **dispatch the OSS tasks** through ``DirectorRole.run`` with the in-lock OSS
     harness — the director plans the ``is_oss`` tasks (tightened scope), each task is admitted by
     the four §S5 fear-map gates, written into a **fork-branch worktree** off the upstream target
     branch, then the per-class verifier runs INSIDE the developer's lock against the uncommitted
     tree; the **bot-identity commit** lands only if the verifier passes (the B4.5 ordering), and a
     fresh-context ``ReviewerRole`` certifies (``completed`` earned twice, Invariant 5).
  3. optionally **publish** the contribution: when a bot-identity commit reached the ``completed``
     terminal this run, push the fork branch and open the pull request under the OPERATOR's
     credential.

The §S5 **identity split** is preserved exactly: the in-lock contribution commit is authored by the
bot identity (``DEVHARNESS_OSS_COMMIT_IDENTITIES``, assigned by the ``DeveloperRole`` after the
verifier passes), while the pull request is opened by the operator (``publish_pull_request`` with the
operator's token). The console adds no write path of its own — Invariant 1 is preserved (the
``DeveloperRole`` alone holds the single write lock and writes inside its isolated fork-branch
worktree, scope-bounded on its realized diff), and every loop event flows through the supplied
``EventBus`` ``emit_sync`` (the console's sole sanctioned write path; spec / plan resolution is
SELECT-only). The console action is the operator pressing "run OSS"; the director, developer, and
reviewer remain the agents.
"""

import asyncio
import json
import os
import time
from pathlib import Path

import msgspec

from devharness.artifacts.plan import OssEnvelope, PlanArtifact
from devharness.console.developer import _server_cfg, emit_client_costs, live_parallax_client
from devharness.models import model_for_tier
from devharness.task_classes.registry import batch_writer_tier
from devharness.console.director import NoSignedSpec, live_reasoning_client
from devharness.health import emit_snapshot
from devharness.oss.intake import fetch_upstream_license, process_intake
from devharness.oss.maintainer import DefaultMaintainerVerifier
from devharness.oss.publish import publish_pull_request
from devharness.roles.developer import DeveloperRole
from devharness.roles.director import DirectorRole
from devharness.roles.reviewer import ReviewerRole
from devharness.sandbox.registry import resolve_launcher
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.task_lifecycle.done_is_earned import complete, reject
from devharness.worktree.isolate import oss_fork_branch
import devharness.verifier.builtin  # noqa: F401  (registers the builtin per-class verifiers)
from devharness.verifier.base import VerifierOk
from devharness.verifier.class_commands import derive_bump_fields, derive_regression_test_ref, language_for_test_command, pass_fail_command, regression_command
from devharness.verifier.runner import run_verifier

_UNSET = object()


class NoPlan(RuntimeError):
    """Raised when the operator runs the OSS path with no plan to source the is_oss tasks from."""


class NoOssTasks(RuntimeError):
    """Raised when the resolved plan / injected task list carries no is_oss task to contribute."""


class ConsoleOss:
    """Operator-driven OSS contribution: drive the §S5 envelope via the real Director/Developer/Reviewer.

    Constructed against the console connection and its ``EventBus`` writer (the emit-only write
    path). ``run`` runs intake hardening, then — only on accept — dispatches the ``is_oss`` tasks
    through ``DirectorRole.run`` with the in-lock OSS harness, and optionally publishes the
    certified contribution. The same operations as ``scripts/run_oss.py``; the §S5 identity split
    (bot commit, operator PR) and Invariant 1 are preserved.
    """

    def __init__(self, conn, writer, *, base_path=None, test_target=None, test_command=None,
                 now_millis=None):
        self._conn = conn
        self._writer = writer  # an EventBus — emit_sync is the only sanctioned write path
        # The local upstream clone the fork branch is cut off; defaults to DEVHARNESS_OSS_UPSTREAM_PATH.
        self._base_path = base_path or os.environ.get("DEVHARNESS_OSS_UPSTREAM_PATH")
        # The verifier's test target (the upstream's own test dir) — the per-class commands read it.
        self._test_target = test_target or os.environ.get("DEVHARNESS_OSS_TEST_TARGET", "tests")
        self._test_command = test_command or ["python", "-m", "pytest", self._test_target, "-q"]
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))

    def run(self, correlation_id, *, spec_id=None, plan_id=None, tasks=None, envelope=None,
            description=None, maintainer_verifier=None, parallax=None, reasoning=None,
            license_fetcher=fetch_upstream_license, sandbox_launcher=_UNSET,
            developer_kwargs=None, intake_correlation_id=None, publish=False,
            publish_fn=publish_pull_request, snapshot=True) -> dict:
        """Drive the §S5 OSS path; return ``{"intake", "plan_id", "published"}``.

        Resolves the latest operator-signed spec (an explicit ``spec_id`` overrides) and the
        ``is_oss`` tasks — from the injected ``tasks`` if given, else extracted from the resolved
        plan for ``correlation_id`` (explicit ``plan_id`` overrides). Runs ``process_intake`` (the
        §S5 front door: cooldown + SPDX license + maintainer verification + injection scan,
        fail-closed); on reject nothing dispatches. On accept, dispatches the tasks through
        ``DirectorRole.run`` with the in-lock OSS harness (four §S5 admission gates → fork-branch
        worktree → in-lock verifier → bot-identity commit after the verifier passes → fresh-context
        reviewer cert). When ``publish`` is set and a certified contribution reached the
        ``completed`` terminal this run, pushes the fork branch and opens the PR under the operator
        credential (the §S5 identity split: bot commit, operator PR).

        Raises ``NoSignedSpec`` when no signed spec exists, ``NoPlan`` when no plan exists to source
        tasks from, and ``NoOssTasks`` when neither the plan nor the injected list carries an
        ``is_oss`` task.
        """
        spec_id = spec_id or self._latest_signed_spec(correlation_id)
        if spec_id is None:
            raise NoSignedSpec(
                f"no signed spec for correlation_id {correlation_id!r} — run + sign research first"
            )
        oss_tasks = self._resolve_oss_tasks(correlation_id, plan_id, tasks)
        envelope = envelope or msgspec.convert(oss_tasks[0]["oss_envelope"], OssEnvelope)
        description = description or oss_tasks[0]["description"]

        # rev 0.3.84: split the quality gate by tier — verifier + non-goals on T1, the fresh-context
        # reviewer on frontier (one guaranteed-frontier pass). An injected parallax (tests) serves both.
        if parallax is not None:
            verifier_parallax = reviewer_parallax = parallax
        else:
            verifier_parallax = live_parallax_client(model=model_for_tier("T1"))
            reviewer_parallax = live_parallax_client()
        maintainer_verifier = maintainer_verifier or DefaultMaintainerVerifier()
        intake_correlation_id = intake_correlation_id or f"intake-{correlation_id}"

        # 1. §S5 intake front door — fail-closed. A reject records no intake, so the director's
        # intake-required check would refuse the task; only an accept records the intake.
        decision = process_intake(
            envelope, description, self._writer, intake_correlation_id=intake_correlation_id,
            correlation_id=correlation_id, maintainer_verifier=maintainer_verifier,
            license_fetcher=license_fetcher, conn=self._conn, now_millis=self._now_millis,
            repo_path=self._base_path,  # F4: scan the upstream clone's README/CONTRIBUTING/AGENTS/CLAUDE
        )
        if decision != "accepted":
            return {"intake": "rejected", "plan_id": None, "published": None}

        # 2. dispatch the is_oss tasks through the real DirectorRole.run with the in-lock harness.
        sandbox = self._sandbox_launcher() if sandbox_launcher is _UNSET else sandbox_launcher
        dev_kwargs = dict(developer_kwargs) if developer_kwargs is not None else self._default_developer_kwargs(sandbox)
        oss_verify, complete_task = self._build_harness(spec_id, correlation_id,
                                                        verifier_parallax, reviewer_parallax)
        dev_kwargs.setdefault("oss_verify_fn", oss_verify)  # without it the dispatch never terminates
        if developer_kwargs is None:
            # route the OSS writer to the batch's class tier (rev 0.3.85): a bugfix/bump contribution
            # writes cheaper; a mixed batch takes the highest tier so a T2 task is never downgraded.
            dev_kwargs["model"] = model_for_tier(
                batch_writer_tier(t.get("task_class") for t in oss_tasks))

        # DirectorRole.run reasons at the decomposition fork — it needs a real reasoning client
        # (the dispatch-only stub yields no result and the run dies before dispatch).
        director = DirectorRole.spawn(
            conn=self._conn, correlation_id=correlation_id,
            reasoning=reasoning or live_reasoning_client(), event_bus=self._writer,
            now_millis=self._now_millis,
        )
        # Wire the non-goals guard's SEMANTIC conformance check to real parallax (as run_oss does):
        # else the OSS path falls to the criteria-blind keyword heuristic for every task.
        director._non_goals_parallax = verifier_parallax

        if snapshot and self._base_path:
            emit_snapshot(self._writer, correlation_id, base_path=str(self._base_path))

        plan_id = asyncio.run(director.run(
            spec_id, correlation_id, tasks=oss_tasks, developer_role_cls=DeveloperRole,
            complete_task=complete_task, developer_kwargs=dev_kwargs,
        ))

        # SC-6: the loop-owned parallax clients' realized spend (in-lock verifier + fresh-context
        # reviewer + non-goals check) — this path never routes through ConsoleDeveloper.dispatch, so
        # its verify_review emission would otherwise never fire for OSS. One emission per DISTINCT
        # client, each with ITS model (rev 0.4.2). Task-scoped only when exactly one OSS task ran
        # (the clients serve the whole list). Zero-cost stubs emit nothing.
        one_task_id = oss_tasks[0].get("task_id", "") if len(oss_tasks) == 1 else ""
        emit_client_costs(self._writer, [verifier_parallax, reviewer_parallax],
                          role="verify_review", correlation_id=correlation_id, task_id=one_task_id)

        # 3. publish only when this run produced a reviewer-certified, completed bot commit. The PR
        # is opened under the OPERATOR credential — the §S5 identity split (the commit was the bot's).
        published = None
        if publish and plan_id is not None:
            published = self._maybe_publish(correlation_id, envelope, publish_fn)
        return {"intake": "accepted", "plan_id": plan_id, "published": published}

    # --- the in-lock OSS harness (mirrors scripts/run_oss.py build_oss_harness) ---

    def _build_harness(self, spec_id, correlation_id, verifier_parallax, reviewer_parallax):
        """The (oss_verify, complete_task) pair: verifier-first in-lock (on ``verifier_parallax``, T1),
        then a fresh-context reviewer (on ``reviewer_parallax``, frontier) — rev 0.3.84."""
        lifecycle = TaskLifecycle()
        pre_commit_ctx = {}  # task_id -> the verifier context captured BEFORE the bot-identity commit

        async def oss_verify(planned_task, developer, conn, event_bus):
            # in-lock, against the uncommitted fork-branch worktree (B4.5); failure auto-rewinds + rejects
            lifecycle.transition(planned_task.task_id, "queued", "running", event_bus, conn)
            vctx = self._oss_vctx(planned_task, developer, verifier_parallax)
            # stash the pre-commit context: the bot commit lands after this passes, so a later
            # realized diff would be EMPTY and the reviewer's feature_spec_claim would fall back to the
            # bare claim and falsely reject. Reuse this realized diff for the reviewer instead.
            pre_commit_ctx[planned_task.task_id] = vctx
            return await run_verifier(
                planned_task.verifier_ref, vctx, event_bus, conn,
                lifecycle=lifecycle, checkpoint=developer.checkpoint,
            )

        async def complete_task(planned_task, developer, conn, event_bus):
            tid, cid = planned_task.task_id, planned_task.correlation_id
            if not isinstance(developer.oss_verify_result, VerifierOk):
                return  # the in-lock verifier failed -> already rewound + terminal-emitted
            vctx = pre_commit_ctx.get(tid) or self._oss_vctx(planned_task, developer, verifier_parallax)
            plan_id = self._latest_plan_id(cid)
            reviewer = ReviewerRole(
                parallax=reviewer_parallax, event_bus=event_bus, conn=conn,
                context=dict(vctx, prior_events=[]), fresh_context=True,
                verifiers=[planned_task.verifier_ref],
            )
            if await reviewer.run(tid, spec_id, plan_id, cid):
                complete(tid, lifecycle, conn, event_bus)
            else:
                reject(tid, "reviewer rejected", lifecycle, conn, event_bus)

        return oss_verify, complete_task

    def _oss_vctx(self, planned_task, developer, parallax):
        """The verifier context for an OSS task — the same per-class fields run_oss supplies."""
        wt = developer.worktree
        vctx = {
            "task_id": planned_task.task_id, "correlation_id": planned_task.correlation_id,
            "cwd": wt.path, "test_command": self._test_command, "parallax": parallax,
            "diff_content": developer._realized_diff(wt),  # verify the realized change, not the proposal
            "spec_claim": planned_task.spec_claim or planned_task.description,
            "claim": planned_task.spec_claim or planned_task.description,
            "regression_test_ref": planned_task.regression_test_ref,
            "dependency_name": planned_task.dependency_name, "target_version": planned_task.target_version,
            "bump_command": planned_task.bump_command, "manifest_path": planned_task.manifest_path,
            "lockfile_path": planned_task.lockfile_path, "checkpoint": developer.checkpoint,
            "conn": developer.conn,  # antibody_screen reads the active library
        }
        lang = language_for_test_command(self._test_command)  # rev 0.4.9 parity with the internal driver
        if planned_task.verifier_ref == "bugfix_regression":
            # rev 0.3.73: derive an empty regression_test_ref from the realized diff (explicit wins)
            ref = planned_task.regression_test_ref or derive_regression_test_ref(
                vctx["diff_content"], lang)
            if ref:
                vctx["regression_command"] = regression_command(ref, language=lang)
        if planned_task.verifier_ref == "refactor_behavior_preserving":
            vctx["pass_fail_command"] = pass_fail_command(self._test_target, language=lang)
        if planned_task.verifier_ref == "dependency_resolves":
            # rev 0.3.70: derive empty class fields from the realized diff (explicit task fields win)
            for k, v in derive_bump_fields(vctx["diff_content"], wt.path).items():
                if not vctx.get(k):
                    vctx[k] = v
        return vctx

    # --- publish (Track 2; the §S5 identity split — operator-opened PR) ---

    def _maybe_publish(self, correlation_id, envelope, publish_fn):
        """If this run produced a bot commit that then reached the ``completed`` terminal
        (reviewer-certified), push the fork branch and open the PR under the operator credential.
        Returns the publish result, or None when nothing certified to publish / not configured."""
        push_repo = os.environ.get("DEVHARNESS_OSS_PUSH_REPO")
        has_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not (push_repo and has_token):
            return None
        row = self._conn.execute(
            "SELECT rowid, payload FROM events WHERE event_type='commit_identity_assigned' "
            "AND correlation_id=? ORDER BY rowid DESC LIMIT 1", (correlation_id,)
        ).fetchone()
        if not row:
            return None  # no accepted contribution committed this run
        commit_rowid, oss_task_id = row[0], json.loads(row[1])["oss_task_id"]
        # the bot commit lands AFTER the verifier but BEFORE reviewer cert; only publish if THIS
        # task then reached `completed` (a terminal_outcome AFTER the commit) — never a rejected
        # branch. Correlation-scoped: plan-local task_ids are not globally unique.
        done = self._conn.execute(
            "SELECT payload FROM events WHERE event_type='terminal_outcome' AND correlation_id=? "
            "AND rowid > ? ORDER BY rowid DESC", (correlation_id, commit_rowid)
        ).fetchall()
        if not any(
            json.loads(p[0]).get("task_id") == oss_task_id and json.loads(p[0]).get("outcome") == "completed"
            for p in done
        ):
            return None  # the contribution was not certified+completed — do not publish
        return publish_fn(
            worktree_path=self._base_path, fork_branch=oss_fork_branch(oss_task_id),
            push_repo=push_repo, pr_repo=os.environ.get("DEVHARNESS_OSS_PR_REPO", push_repo),
            base_branch=envelope.target_branch,
            fork_owner=os.environ.get("DEVHARNESS_OSS_FORK_OWNER", push_repo.split("/")[0]),
            title=f"devharness OSS contribution: {oss_task_id}",
            body="Automated contribution opened by the devharness OSS loop (verifier-passed, reviewer-certified).",
            oss_task_id=oss_task_id, upstream_repo=envelope.upstream_repo,
            event_bus=self._writer, correlation_id=correlation_id,
        )

    # --- kwargs / sandbox (mirror scripts/run_oss.py + ConsoleDeveloper) ---

    def _default_developer_kwargs(self, sandbox) -> dict:
        """The live operator developer kwargs: write into the upstream clone with advisory MCP
        servers wired from ~/.claude.json (the ACI server is always bound in-process)."""
        return {
            "base_path": str(self._base_path),
            "sandbox_launcher": sandbox,
            "mcp_server_configs": {
                "parallax": _server_cfg("parallax"),
                "mcp-reasoning": _server_cfg("mcp-reasoning"),
            },
        }

    def _sandbox_launcher(self):
        """Opt-in §S5 sandbox routing: host by default (DEVHARNESS_SANDBOX_PREFERRED selects a tier)."""
        pref = os.environ.get("DEVHARNESS_SANDBOX_PREFERRED")
        return resolve_launcher(pref) if pref else None

    # --- task / spec / plan resolution (SELECT-only; no event-store or projection writes) ---

    def _resolve_oss_tasks(self, correlation_id, plan_id, tasks):
        """The is_oss task dicts to dispatch — the injected list, else the resolved plan's is_oss tasks."""
        if tasks is not None:
            oss = [t for t in tasks if t.get("is_oss")]
        else:
            _pid, plan = self._resolve_plan(correlation_id, plan_id)
            oss = [msgspec.to_builtins(t) for t in plan.tasks if getattr(t, "is_oss", False)]
        if not oss:
            raise NoOssTasks(
                f"no is_oss task for correlation_id {correlation_id!r} — the plan has no OSS contribution"
            )
        return oss

    def _latest_signed_spec(self, correlation_id):
        row = self._conn.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE artifact_type = 'spec' AND correlation_id = ? AND signed = 1 "
            "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1",
            (correlation_id,),
        ).fetchone()
        return row[0] if row else None

    def _latest_plan_id(self, correlation_id):
        row = self._conn.execute(
            "SELECT artifact_id FROM artifacts WHERE artifact_type = 'plan' AND correlation_id = ? "
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
