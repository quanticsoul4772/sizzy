"""Drive an OSS contribution through the §S5 envelope (#H1).

`oss/intake.py:process_intake` and the OSS dispatch path existed but had **zero production callers** —
nothing ran the intake front door or dispatched an `is_oss` task on a real path. This is that driver.

`drive_oss` is the testable core: run intake (cooldown + SPDX license + maintainer verification +
injection scan, fail-closed); on accept, dispatch the OSS tasks through `DirectorRole.run` with the
in-lock OSS harness — the per-class verifier runs INSIDE the developer's lock against the uncommitted
fork-branch worktree (B4.5), the bot-identity commit lands only if it passes, then a fresh-context
`ReviewerRole` certifies. On reject, nothing dispatches.

`main()` wires real production boundaries: maintainer verification via `DefaultMaintainerVerifier`
(the `DEVHARNESS_OSS_MAINTAINERS` allowlist — NOT a test fake) and the opt-in sandbox launcher. What a
LIVE run still needs from the operator is config, not code: a local upstream clone
(`DEVHARNESS_OSS_UPSTREAM_PATH`), `DEVHARNESS_OSS_COMMIT_IDENTITIES`, and — for real §S5 containment —
`DEVHARNESS_SANDBOX_PREFERRED=wsl` (else the sandbox gate fail-closes the dispatch).

Run:  python scripts/run_oss.py  (a stray ANTHROPIC_API_KEY is cleared at startup)
"""

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime"))

import msgspec  # noqa: E402

from devharness import boot  # noqa: E402
from devharness.mcp.config import MCPConfigError, server_cfg  # noqa: E402
from devharness.artifacts.plan import OssEnvelope, PlanArtifact  # noqa: E402
from devharness.cli._bus import projected_bus  # noqa: E402
from devharness.console.developer import emit_client_costs  # noqa: E402
from devharness.mcp.mcp_reasoning import MCPReasoningClient  # noqa: E402
from devharness.mcp.parallax import ParallaxClient  # noqa: E402
from devharness.models import model_for_tier  # noqa: E402
from devharness.task_classes.registry import batch_writer_tier  # noqa: E402
from devharness.migrate import migrate  # noqa: E402
from devharness.oss.intake import fetch_upstream_license, process_intake  # noqa: E402
from devharness.oss.maintainer import DefaultMaintainerVerifier  # noqa: E402
from devharness.oss.publish import publish_pull_request  # noqa: E402
from devharness.sandbox.registry import resolve_launcher  # noqa: E402
from devharness.worktree.isolate import oss_fork_branch  # noqa: E402
from devharness.roles.developer import DeveloperRole  # noqa: E402
from devharness.roles.director import DirectorRole  # noqa: E402
from devharness.roles.integration import integrate  # noqa: E402
from devharness.roles.reviewer import ReviewerRole  # noqa: E402
from devharness.task_lifecycle.base import TaskLifecycle  # noqa: E402
from devharness.task_lifecycle.done_is_earned import complete, reject  # noqa: E402
import devharness.verifier.builtin  # noqa: E402,F401  (registers the per-class verifiers)
from devharness.verifier.base import VerifierOk  # noqa: E402
from devharness.verifier.class_commands import derive_bump_fields, derive_regression_test_ref, language_for_test_command, pass_fail_command, regression_command  # noqa: E402
from devharness.verifier.runner import run_verifier  # noqa: E402

CORRELATION_ID = os.environ.get("DEVHARNESS_CORRELATION_ID", "oss")
TEST_TARGET = os.environ.get("DEVHARNESS_OSS_TEST_TARGET", "tests")
TEST_COMMAND = ["python", "-m", "pytest", TEST_TARGET, "-q"]


def _oss_vctx(planned_task, developer, parallax):
    """The verifier context for an OSS task — the same per-class fields run_developer supplies."""
    wt = developer.worktree
    vctx = {
        "task_id": planned_task.task_id, "correlation_id": planned_task.correlation_id, "cwd": wt.path,
        "test_command": TEST_COMMAND, "parallax": parallax,
        "diff_content": developer._realized_diff(wt),  # #C0
        "spec_claim": planned_task.spec_claim or planned_task.description,
        "claim": planned_task.spec_claim or planned_task.description,
        "regression_test_ref": planned_task.regression_test_ref,
        "dependency_name": planned_task.dependency_name, "target_version": planned_task.target_version,
        "bump_command": planned_task.bump_command, "manifest_path": planned_task.manifest_path,
        "lockfile_path": planned_task.lockfile_path, "checkpoint": developer.checkpoint,
        "conn": developer.conn,  # #M7: antibody_screen reads the active library
    }
    lang = language_for_test_command(TEST_COMMAND)  # rev 0.4.9 parity with the internal driver
    if planned_task.verifier_ref == "bugfix_regression":  # #C0f
        # rev 0.3.73: derive an empty regression_test_ref from the realized diff (explicit wins)
        ref = planned_task.regression_test_ref or derive_regression_test_ref(
            vctx["diff_content"], lang)
        if ref:
            vctx["regression_command"] = regression_command(ref, language=lang)
    if planned_task.verifier_ref == "refactor_behavior_preserving":
        vctx["pass_fail_command"] = pass_fail_command(TEST_TARGET, language=lang)
    if planned_task.verifier_ref == "dependency_resolves":
        # rev 0.3.70: derive empty class fields from the realized diff (explicit task fields win)
        for k, v in derive_bump_fields(vctx["diff_content"], wt.path).items():
            if not vctx.get(k):
                vctx[k] = v
    return vctx


def build_oss_harness(verifier_parallax, reviewer_parallax, spec_id, plan_id):
    """The (oss_verify_fn, complete_task) pair: verifier-first in-lock (verifier_parallax, T1), then a
    real fresh-context reviewer (reviewer_parallax, frontier) — rev 0.3.84."""
    lifecycle = TaskLifecycle()
    pre_commit_ctx = {}  # task_id -> the verifier context captured BEFORE the bot-identity commit

    async def oss_verify(planned_task, developer, conn, event_bus):
        # in-lock, against the uncommitted fork-branch worktree (B4.5); failure auto-rewinds + rejects
        lifecycle.transition(planned_task.task_id, "queued", "running", event_bus, conn)
        vctx = _oss_vctx(planned_task, developer, verifier_parallax)
        # stash the pre-commit context: the bot commit lands after this passes, so a later
        # _realized_diff would be EMPTY and the reviewer's feature_spec_claim would fall back to the
        # bare claim and falsely reject. Reuse this realized diff for the reviewer instead.
        pre_commit_ctx[planned_task.task_id] = vctx
        return await run_verifier(planned_task.verifier_ref, vctx, event_bus, conn,
                                  lifecycle=lifecycle, checkpoint=developer.checkpoint)

    async def complete_task(planned_task, developer, conn, event_bus):
        tid, cid = planned_task.task_id, planned_task.correlation_id
        if not isinstance(developer.oss_verify_result, VerifierOk):
            return  # the in-lock verifier failed -> already rewound + terminal-emitted
        vctx = pre_commit_ctx.get(tid) or _oss_vctx(planned_task, developer, verifier_parallax)
        reviewer = ReviewerRole(parallax=reviewer_parallax, event_bus=event_bus, conn=conn,
                                context=dict(vctx, prior_events=[]),
                                fresh_context=True, verifiers=[planned_task.verifier_ref])
        if await reviewer.run(tid, spec_id, plan_id, cid):
            complete(tid, lifecycle, conn, event_bus)
        else:
            reject(tid, "reviewer rejected", lifecycle, conn, event_bus)

    return oss_verify, complete_task


async def drive_oss(director, *, signed_spec_id, envelope, description, tasks, maintainer_verifier,
                    conn, event_bus, developer_role_cls, complete_task, developer_kwargs,
                    intake_correlation_id, correlation_id, license_fetcher=fetch_upstream_license,
                    now_millis=None, repo_path=None) -> dict:
    """Run intake, then dispatch the OSS tasks only if it accepts. The new wiring #H1 adds."""
    decision = process_intake(
        envelope, description, event_bus, intake_correlation_id=intake_correlation_id,
        correlation_id=correlation_id, maintainer_verifier=maintainer_verifier, license_fetcher=license_fetcher,
        conn=conn, now_millis=now_millis, repo_path=repo_path,
    )
    if decision != "accepted":
        return {"intake": "rejected", "plan_id": None}
    plan_id = await director.run(
        signed_spec_id, correlation_id, tasks=tasks, developer_role_cls=developer_role_cls,
        complete_task=complete_task, developer_kwargs=developer_kwargs,
    )
    return {"intake": "accepted", "plan_id": plan_id}


def _server_cfg(name: str) -> dict:
    """rev 0.4.25: via the single config source (DEVHARNESS_MCP_CONFIG, else ~/.claude.json)."""
    try:
        return server_cfg(name)
    except MCPConfigError as exc:
        sys.exit(str(exc))


def _stub_reasoning() -> MCPReasoningClient:
    async def _q(*, prompt, options):  # dispatch never reasons
        if False:
            yield None
    return MCPReasoningClient(query_fn=_q)


def _sandbox_launcher():
    """Opt-in §S5 sandbox routing (#1a/C6): host by default (the mock launcher is fail-closed)."""
    pref = os.environ.get("DEVHARNESS_SANDBOX_PREFERRED")
    return resolve_launcher(pref) if pref else None


def main() -> int:
    # A stray ANTHROPIC_API_KEY kills the SDK subprocess at launch (exit 1); the harness bills
    # through the claude.ai login. Same posture as the console (tui.py) — rev 0.3.57.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    db_path = os.environ.get("DEVHARNESS_DB") or str(REPO / "var" / "devharness.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    migrate(conn)
    boot.run_boot_checks()  # #C4
    bus = projected_bus(conn)

    from devharness.health import emit_snapshot, leak_warning  # resource telemetry (every driver, not just developer)
    snap = emit_snapshot(bus, CORRELATION_ID, base_path=str(REPO))
    print(f"[run_oss] resources: {snap['process_count']} procs · {snap['git_process_count']} git · "
          f"{snap['worktree_count']} worktrees · {snap['free_memory_mb']}MB free")
    if (warn := leak_warning(snap)):
        print(f"[run_oss] ⚠ {warn}")

    spec_row = conn.execute(
        "SELECT artifact_id FROM artifacts WHERE artifact_type='spec' AND correlation_id=? AND signed=1 "
        "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1", (CORRELATION_ID,)).fetchone()
    if not spec_row:
        sys.exit("no signed spec for the OSS correlation — run + sign research first")
    plan_row = conn.execute(
        "SELECT artifact_id, payload_json FROM artifacts WHERE artifact_type='plan' AND correlation_id=? "
        "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1", (CORRELATION_ID,)).fetchone()
    if not plan_row:
        sys.exit("no plan for the OSS correlation — run run_director.py first")
    spec_id, plan_id = spec_row[0], plan_row[0]

    plan = msgspec.convert(json.loads(plan_row[1]), PlanArtifact)
    oss_tasks = [t for t in plan.tasks if getattr(t, "is_oss", False)]
    if not oss_tasks:
        sys.exit("the plan for this correlation has no is_oss tasks")
    envelope = msgspec.convert(oss_tasks[0].oss_envelope, OssEnvelope)

    # Maintainer verification is REAL + env-backed (DefaultMaintainerVerifier over DEVHARNESS_OSS_MAINTAINERS),
    # not a test-only fake. The genuinely operator-provided pieces are a local upstream clone (the fork
    # branches off it) and, for real §S5 containment, a sandbox launcher (C6: DEVHARNESS_SANDBOX_PREFERRED=wsl).
    upstream = os.environ.get("DEVHARNESS_OSS_UPSTREAM_PATH")
    if not upstream:
        sys.exit("set DEVHARNESS_OSS_UPSTREAM_PATH to a local clone of the upstream repo. Maintainer "
                 "verification uses DEVHARNESS_OSS_MAINTAINERS; set DEVHARNESS_SANDBOX_PREFERRED=wsl for real "
                 "§S5 containment (else the sandbox gate fail-closes the dispatch).")

    maintainer_verifier = DefaultMaintainerVerifier()  # DEVHARNESS_OSS_MAINTAINERS allowlist
    if not maintainer_verifier._maintainers:
        print("[run_oss] WARNING: DEVHARNESS_OSS_MAINTAINERS is empty — every intake will reject (fail-closed).")

    # rev 0.3.84: verifier on T1, reviewer on frontier (split the quality gate by tier)
    verifier_parallax = ParallaxClient(mcp_servers={"parallax": _server_cfg("parallax")}, model=model_for_tier("T1"))
    reviewer_parallax = ParallaxClient(mcp_servers={"parallax": _server_cfg("parallax")})
    oss_verify, complete_task = build_oss_harness(verifier_parallax, reviewer_parallax, spec_id, plan_id)
    # director.run reasons at the decomposition fork (reasoning_decision) — it needs the REAL mcp-reasoning
    # client, not a stub (the stub yields no ResultMessage and the run dies before dispatch).
    reasoning = MCPReasoningClient(mcp_servers={"mcp-reasoning": _server_cfg("mcp-reasoning")})
    director = DirectorRole.spawn(conn=conn, correlation_id=CORRELATION_ID, reasoning=reasoning, event_bus=bus)
    director._non_goals_parallax = verifier_parallax  # #3a: OSS gets the criteria-aware semantic non-goals check too
    # (else the OSS path falls to the criteria-blind keyword heuristic for every task — audit finding)

    result = asyncio.run(drive_oss(
        director, signed_spec_id=spec_id, envelope=envelope, description=oss_tasks[0].description,
        tasks=[msgspec.to_builtins(t) for t in oss_tasks], maintainer_verifier=maintainer_verifier,
        conn=conn, event_bus=bus, developer_role_cls=DeveloperRole, complete_task=complete_task,
        developer_kwargs={"base_path": upstream, "sandbox_launcher": _sandbox_launcher(),
                          "oss_verify_fn": oss_verify,  # the in-lock verifier — without it the dispatch never terminates
                          # route the OSS writer to the batch's class tier (rev 0.3.85; highest-wins)
                          "model": model_for_tier(batch_writer_tier(t.task_class for t in oss_tasks)),
                          "mcp_server_configs": {"parallax": _server_cfg("parallax"),
                                                 "mcp-reasoning": _server_cfg("mcp-reasoning")}},
        intake_correlation_id=f"intake-{CORRELATION_ID}", correlation_id=CORRELATION_ID,
        repo_path=upstream))  # F4: scan the upstream clone's README/CONTRIBUTING/AGENTS/CLAUDE at intake

    # SC-6: the loop-owned parallax clients' realized spend (in-lock verifier + fresh-context
    # reviewer + non-goals check). One emission per DISTINCT client, each with ITS model (rev 0.4.2).
    # Task-scoped only when exactly one OSS task ran — the clients serve the whole list, so a
    # multi-task total pinned to one task_id would fabricate attribution.
    emit_client_costs(bus, [verifier_parallax, reviewer_parallax], role="verify_review",
                      correlation_id=CORRELATION_ID,
                      task_id=oss_tasks[0].task_id if len(oss_tasks) == 1 else "")

    print(f"[run_oss] intake: {result['intake']}   plan: {result['plan_id']}")

    # publish ONLY when intake accepted + dispatched this run (else a rejected intake would scrape a prior
    # run's commit and publish a stale branch)
    pub = _maybe_publish(conn, envelope, upstream, bus) if result["plan_id"] is not None else None
    if pub:
        print(f"[run_oss] PR opened: {pub['pr_url']}")
    elif os.environ.get("DEVHARNESS_OSS_PUSH_REPO"):
        print("[run_oss] publish skipped (no reviewer-certified completed contribution / no GH token)")
    return 0 if result["plan_id"] is not None else 1


def _maybe_publish(conn, envelope, upstream_path, event_bus):
    """Track 2: if GH_TOKEN + DEVHARNESS_OSS_PUSH_REPO are set and the loop produced a bot commit that then
    reached the `completed` terminal (reviewer-certified), push the contribution's fork-branch and open the
    PR. push_repo = the fork to push to; pr_repo defaults to it (a same-repo PR), or set
    DEVHARNESS_OSS_PR_REPO for a cross-repo fork PR. Returns the publish result, or None when not configured
    / nothing certified to publish."""
    push_repo = os.environ.get("DEVHARNESS_OSS_PUSH_REPO")
    has_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not (push_repo and has_token):
        return None
    row = conn.execute(
        "SELECT rowid, payload FROM events WHERE event_type='commit_identity_assigned' AND correlation_id=? "
        "ORDER BY rowid DESC LIMIT 1", (CORRELATION_ID,)).fetchone()
    if not row:
        return None  # no accepted contribution committed this run
    commit_rowid, oss_task_id = row[0], json.loads(row[1])["oss_task_id"]
    # the bot commit lands AFTER the verifier but BEFORE reviewer cert; only publish if THIS task then
    # reached `completed` (a terminal_outcome AFTER the commit) — never a reviewer-rejected/aborted branch
    # correlation-scoped (audit): plan-local task_ids (t1, …) are not globally unique, so without the
    # correlation_id filter a `completed` terminal for a COLLIDING task_id in a DIFFERENT correlation could
    # satisfy this and publish an uncertified branch. Scope to THIS run, matching the commit-identity query.
    done = conn.execute(
        "SELECT payload FROM events WHERE event_type='terminal_outcome' AND correlation_id=? AND rowid > ? "
        "ORDER BY rowid DESC", (CORRELATION_ID, commit_rowid)).fetchall()
    if not any(json.loads(p[0]).get("task_id") == oss_task_id and json.loads(p[0]).get("outcome") == "completed"
               for p in done):
        return None  # the contribution was not certified+completed — do not publish
    return publish_pull_request(
        worktree_path=upstream_path, fork_branch=oss_fork_branch(oss_task_id),
        push_repo=push_repo, pr_repo=os.environ.get("DEVHARNESS_OSS_PR_REPO", push_repo),
        base_branch=envelope.target_branch,
        fork_owner=os.environ.get("DEVHARNESS_OSS_FORK_OWNER", push_repo.split("/")[0]),
        title=f"devharness OSS contribution: {oss_task_id}",
        body="Automated contribution opened by the devharness OSS loop (verifier-passed, reviewer-certified).",
        oss_task_id=oss_task_id, upstream_repo=envelope.upstream_repo,
        event_bus=event_bus, correlation_id=CORRELATION_ID)


if __name__ == "__main__":
    raise SystemExit(main())
