"""End-to-end guard: a feature reaches `completed` through the REAL loop, incl. the real reviewer.

This is the regression lock for the four stacked bugs (C0/C0b/C0c/C0d) that made the feature class
unable to complete. Unlike test_b3_feature (which fabricates reviewer_certified and feeds a dict
verdict), this drives the real path:
  - feature_spec_claim with the realized diff in context (C0),
  - a fake parallax client returning the REAL rendered verdict text, so parallax_passed's prose/JSON
    parsing is exercised (C0b),
  - the real ReviewerRole.run for the second half of "done earned twice", so its claim grounding is
    exercised (C0d).
If any of the four regress, the completion assertion here fails.
"""

import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers feature_spec_claim, parallax_verify, test_suite)
from devharness.events.bus import EventBus, verify_chain
from devharness.mcp.base import CallResult
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.roles.director import DirectorRole
from devharness.roles.reviewer import ReviewerRole
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.task_lifecycle.done_is_earned import complete, reject
from devharness.verifier.base import VerifierOk
from devharness.verifier.runner import run_verifier

CID = "corr-loop-complete"
# the worktree "test suite": passes iff app.py declares foo() returning 42
_TEST_CMD = ["python", "-c", "import sys; sys.exit(0 if 'return 42' in open('app.py').read() else 1)"]

# the REAL rendered shapes parallax actually returns — these are what broke parallax_passed
_SUPPORTED_PROSE = "Verdict: **supported** (confidence 1.0, 3/3 passes agree, no refuting findings). The diff implements the claim."
_REFUTED_JSON = '{"confidence":1,"findings":["The diff does not implement the claim; no such change is present."]}'


class _FakeParallaxClient:
    """A parallax CLIENT (context['parallax']) whose verify returns the real rendered verdict text.

    Accepts a single verdict (used for every call) or a list consumed in order — the latter lets a
    test give the developer's acceptance one verdict and the reviewer's certification a different one
    (one parallax.verify call each).
    """

    def __init__(self, verdicts):
        self._verdicts = verdicts if isinstance(verdicts, list) else [verdicts]
        self._i = 0

    async def verify(self, claim, context=""):  # context: untrusted text passed separately (injection fix)
        v = self._verdicts[min(self._i, len(self._verdicts) - 1)]
        self._i += 1
        return CallResult(output=v, cost_usd=0.0, usage=None, is_error=False)


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


def _existing_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "app.py").write_text("def foo():\n    return 0\n")
    run("add", "-A")
    run("commit", "-m", "base")
    run("branch", "feature-base")
    return repo


def _make_complete_task(parallax, lifecycle):
    """Mirror scripts/run_developer.py: real verifier-first acceptance + real ReviewerRole cert."""

    async def complete_task(planned_task, developer, conn, event_bus):
        tid, cid = planned_task.task_id, planned_task.correlation_id
        wt = developer.worktree
        lifecycle.transition(tid, "queued", "running", event_bus, conn)
        vctx = {
            "task_id": tid, "correlation_id": cid, "cwd": wt.path, "test_command": _TEST_CMD,
            "parallax": parallax,
            "diff_content": developer._realized_diff(wt),  # C0: the realized change
            "spec_claim": planned_task.spec_claim or planned_task.description,
            "claim": planned_task.spec_claim or planned_task.description,
        }
        result = await run_verifier(planned_task.verifier_ref, vctx, event_bus, conn,
                                    lifecycle=lifecycle, checkpoint=developer.checkpoint)
        if not isinstance(result, VerifierOk):
            return
        # the real reviewer, fresh context, re-running the same acceptance verifier (done earned twice)
        reviewer = ReviewerRole(parallax=parallax, event_bus=event_bus, conn=conn,
                                context=dict(vctx, prior_events=[]), fresh_context=True,
                                verifiers=[planned_task.verifier_ref])
        certified = await reviewer.run(tid, "spec-1", "plan-1", cid)
        if certified:
            complete(tid, lifecycle, conn, event_bus)
        else:
            reject(tid, "reviewer rejected", lifecycle, conn, event_bus)

    return complete_task


def _run(tmp_path, *, feature_body, verdicts):
    repo = _existing_repo(tmp_path)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    register_builtin_task_classes()
    conn.execute("INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) VALUES ('spec-1','spec',1,'{}',?,1,1)", (CID,))
    conn.commit()
    bus.emit_sync("spec_signed", {"spec_id": "spec-1", "signer": "operator", "signed_at_millis": 1}, correlation_id=CID)

    def write_hook(editor, shell, test_runner):
        editor.write_file("app.py", feature_body, predicted_success=0.9)
        # test_coverage axis (rev 0.3.49): the realized diff must add a new test, or the developer's own
        # acceptance never gets past feature_spec_claim's test_coverage check.
        editor.write_file("tests/test_foo.py", "def test_foo():\n    assert True\n", predicted_success=0.9)

    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    tasks = [{"task_class": "feature", "description": "foo() returns 42",
              "scope_boundary": ["app.py", "tests/test_foo.py"], "dependencies": []}]
    plan_id = asyncio.run(director.run(
        "spec-1", CID, tasks=tasks, developer_role_cls=DeveloperRole,
        complete_task=_make_complete_task(_FakeParallaxClient(verdicts), TaskLifecycle()),
        developer_kwargs={"base_path": str(repo), "base_ref": "feature-base", "query_fn": _noop_query(), "write_hook": write_hook},
    ))
    return conn, registry, plan_id


def test_feature_completes_end_to_end_through_real_reviewer(tmp_path):
    # tests pass AND parallax renders `supported` (prose) -> developer accepts -> real reviewer certifies
    conn, registry, plan_id = _run(tmp_path, feature_body="def foo():\n    return 42\n", verdicts=_SUPPORTED_PROSE)
    task_id = f"{CID}-t0"

    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)).fetchone()[0] == "pass"
    # the REAL reviewer certified (not a fabricated event) — guards C0d + C0b on the reviewer's axis
    assert conn.execute("SELECT verdict FROM proj_reviewer_certs WHERE task_id=?", (task_id,)).fetchone()[0] == "certified"
    assert conn.execute("SELECT current_state, outcome FROM proj_task_lifecycle WHERE task_id=?", (task_id,)).fetchone() == ("completed", "completed")
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone()[0] == "completed"
    assert verify_chain(conn) == conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert check_projection_rebuild_parity(conn, registry) is True


def test_reviewer_rejects_a_refutation_verdict(tmp_path):
    # tests pass so the developer accepts, but the reviewer's parallax renders a refutation (JSON)
    # -> the real reviewer must reject -> not completed. Proves the reviewer genuinely runs + can fail.
    # developer's acceptance sees `supported`; the reviewer's fresh parallax call sees a refutation
    conn, registry, plan_id = _run(tmp_path, feature_body="def foo():\n    return 42\n", verdicts=[_SUPPORTED_PROSE, _REFUTED_JSON])
    task_id = f"{CID}-t0"

    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)).fetchone()[0] == "pass"
    assert conn.execute("SELECT count(*) FROM proj_reviewer_certs WHERE task_id=? AND verdict='certified'", (task_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT current_state FROM proj_task_lifecycle WHERE task_id=?", (task_id,)).fetchone()[0] == "rejected"
    assert check_projection_rebuild_parity(conn, registry) is True
