"""B4.8 cut-line acceptance: the full OSS contribution loop on a synthetic external repo.

A multi-task OSS plan (an OSS feature + an OSS bugfix, each is_oss=True) runs end to end: intake
hardening → director plans with the BUILD verifier + tightened scope → OSS-gated admission →
fork-branch worktree off the upstream target branch → worker writes → **verifier runs inside the lock
against the uncommitted tree** → bot-identity commit ONLY on pass (B4.5 ordering fix) → reviewer cert →
integrate. Asserts the cross-cutting invariants (1,3,4,5,6,7,8,9,10,13,14,15,16,18) + the OSS
projections + the 24/0 boot ledger.
"""

import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
import devharness.verifier.builtin  # noqa: F401
from devharness.artifacts.plan import OssEnvelope
from devharness.events.bus import EventBus, verify_chain
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.oss.intake import process_intake
from devharness.oss.maintainer import TestMaintainerVerifier
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.roles.director import DirectorRole
from devharness.sandbox import registry as sandbox_registry
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.task_lifecycle.done_is_earned import complete
from devharness.verifier.base import VerifierOk
from devharness.verifier.runner import run_verifier

CID = "corr-b4-accept"
REPO_SLUG = "octo/widget"
FEATURE_SUITE = ["python", "-B", "-c", "import sys; sys.exit(0 if 'def added' in open('feature.py').read() else 1)"]
BUG_REGRESSION = ["python", "-B", "-c", "import sys; sys.exit(0 if 'return 42' in open('bug.py').read() else 1)"]
SUITE_OK = ["python", "-c", "import sys; sys.exit(0)"]
_ENV = OssEnvelope(upstream_repo=REPO_SLUG, license_spdx="MIT", requester_id="alice", target_branch="main")
_WRITES = {"feature": ("feature.py", "# target\ndef added():\n    return 1\n"),
           "bugfix": ("bug.py", "def foo():\n    return 42\n")}


class _Result:
    def __init__(self, passed):
        self.output = {"verified": passed}
        self.cost_usd = 0.0
        self.is_error = False


class _FakeParallax:
    async def verify(self, claim, context=""):
        return _Result(True)


class _R:
    total_cost_usd = 0.0
    result = "ok"
    usage = {"input_tokens": 1, "output_tokens": 1}
    is_error = False


def _reasoning():
    async def query(*, prompt, options):
        yield _R()
    return MCPReasoningClient(query_fn=query)


def _noop_query():
    async def query(*, prompt, options):
        if False:
            yield None
    return query


def _upstream(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "operator@local")
    run("config", "user.name", "operator")
    run("checkout", "-b", "main")
    (repo / "feature.py").write_text("# target\n")
    (repo / "bug.py").write_text("def foo():\n    return 0\n")  # the bug
    run("add", "-A")
    run("commit", "-m", "base")
    return repo


def _build_ctx(planned_task, developer):
    tid, cid, tc = planned_task.task_id, planned_task.correlation_id, planned_task.task_class
    wt = developer.worktree.path
    if tc == "feature":
        return {"task_id": tid, "correlation_id": cid, "cwd": wt, "test_command": FEATURE_SUITE,
                "parallax": _FakeParallax(), "spec_claim": planned_task.spec_claim,
                "checkpoint": developer.checkpoint,
                # test_coverage axis (rev 0.3.49): hand-built ctx, not derived via _realized_diff(wt).
                "diff_content": ("diff --git a/tests/test_feature.py b/tests/test_feature.py\n"
                                 "+++ b/tests/test_feature.py\n+def test_added():\n+    assert True\n")}
    return {"task_id": tid, "correlation_id": cid, "cwd": wt, "checkpoint": developer.checkpoint,
            "regression_command": BUG_REGRESSION, "test_command": SUITE_OK}


def _make_harness():
    lifecycle = TaskLifecycle()

    async def oss_verify(planned_task, developer, conn, event_bus):
        # runs INSIDE the developer's lock, against the uncommitted worktree (B4.5 ordering fix)
        tid = planned_task.task_id
        lifecycle.transition(tid, "queued", "running", event_bus, conn)
        return await run_verifier(planned_task.verifier_ref, _build_ctx(planned_task, developer),
                                  event_bus, conn, lifecycle=lifecycle, checkpoint=developer.checkpoint)

    async def complete_task(planned_task, developer, conn, event_bus):
        # the verifier already ran in-lock (developer.oss_verify_result); reviewer cert + complete here
        tid, cid = planned_task.task_id, planned_task.correlation_id
        if isinstance(developer.oss_verify_result, VerifierOk):
            event_bus.emit_sync("reviewer_certified", {"task_id": tid, "reviewer_session_id": "rs", "evidence": {}, "correlation_id": cid, "certified_at_millis": 1}, correlation_id=cid)
            complete(tid, lifecycle, conn, event_bus)

    return oss_verify, complete_task


class _OssDeveloper(DeveloperRole):
    def __init__(self, **kwargs):
        kwargs["write_hook"] = self._route
        super().__init__(**kwargs)
        self._planned = None

    async def run(self, planned_task, correlation_id):
        self._planned = planned_task
        await super().run(planned_task, correlation_id)

    def _route(self, editor, shell, test_runner):
        path, body = _WRITES[self._planned.task_class]
        editor.write_file(path, body)


def _run(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: True)
    monkeypatch.setenv("DEVHARNESS_OSS_CAPS_POLL_INTERVAL_SECONDS", "0.001")
    import json
    monkeypatch.setenv("DEVHARNESS_OSS_COMMIT_IDENTITIES", json.dumps({REPO_SLUG: {"name": "widget-bot", "email": "bot@octo.example"}}))

    repo = _upstream(tmp_path)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    register_builtin_task_classes()
    conn.execute("INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) VALUES ('spec-1','spec',1,'{}',?,1,1)", (CID,))
    conn.commit()
    bus.emit_sync("spec_signed", {"spec_id": "spec-1", "signer": "operator", "signed_at_millis": 1}, correlation_id=CID)

    verifier = TestMaintainerVerifier([(REPO_SLUG, "alice")])
    for i in range(2):
        assert process_intake(_ENV, "add a small helper", bus, intake_correlation_id=f"intake-{i}",
                              correlation_id=CID, maintainer_verifier=verifier, license_fetcher=lambda r: _ENV.license_spdx,
                              now_millis=lambda: 1, conn=conn) == "accepted"

    env_dict = {"upstream_repo": REPO_SLUG, "license_spdx": "MIT", "requester_id": "alice", "target_branch": "main"}
    tasks = [
        {"task_class": "feature", "description": "added() helper", "scope_boundary": ["feature.py"], "dependencies": [], "is_oss": True, "oss_envelope": dict(env_dict)},
        {"task_class": "bugfix", "description": "foo returns 42", "scope_boundary": ["bug.py"], "dependencies": [f"{CID}-t0"], "is_oss": True, "oss_envelope": dict(env_dict)},
    ]
    oss_verify, complete_task = _make_harness()
    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    plan_id = asyncio.run(director.run(
        "spec-1", CID, tasks=tasks, developer_role_cls=_OssDeveloper, complete_task=complete_task,
        developer_kwargs={"base_path": str(repo), "query_fn": _noop_query(), "oss_verify_fn": oss_verify},
    ))
    return conn, registry, plan_id, repo


def test_oss_feature_and_bugfix_loop_completes(tmp_path, monkeypatch):
    conn, registry, plan_id, repo = _run(tmp_path, monkeypatch)
    task_ids = [f"{CID}-t0", f"{CID}-t1"]

    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone()[0] == "completed"
    # both classes verified (feature via spec-claim, bugfix via the stash-based regression baseline)
    verifiers = dict(conn.execute("SELECT task_id, verifier_name FROM proj_verifier_outcomes"))
    assert verifiers == {f"{CID}-t0": "feature_spec_claim", f"{CID}-t1": "bugfix_regression"}
    for tid in task_ids:
        assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (tid,)).fetchone()[0] == "pass"
        assert conn.execute("SELECT verdict FROM proj_reviewer_certs WHERE task_id=?", (tid,)).fetchone()[0] == "certified"
        assert conn.execute("SELECT current_state FROM proj_task_lifecycle WHERE task_id=?", (tid,)).fetchone()[0] == "completed"

    assert conn.execute("SELECT count(*) FROM proj_oss_intake").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM proj_oss_worktrees").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM proj_commit_identity").fetchone()[0] == 2
    assert {r[0] for r in conn.execute("SELECT identity_name FROM proj_commit_identity")} == {"widget-bot"}

    # Inv 7 + 9 + 8 + 18
    assert verify_chain(conn) == conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert all(r[0] for r in conn.execute("SELECT correlation_id FROM events"))
    assert check_projection_rebuild_parity(conn, registry) is True
    assert len(boot.registered_check_names()) == len(boot.REQUIRED_GATES)
    assert boot.check_dashboard_tile_coverage() is True
    real = sum(1 for checks in boot._REGISTRY.values() for fn in checks.values() if fn is not boot._unmapped)
    assert real == len(boot.registered_check_names())


def test_oss_gates_fired_at_admission(tmp_path, monkeypatch):
    conn, _registry, _plan_id, _repo = _run(tmp_path, monkeypatch)
    fired = {r[0] for r in conn.execute("SELECT gate FROM proj_gate_fires")}
    assert {"workflow_guard", "secret_guard", "scope_guard", "sandbox"} <= fired
