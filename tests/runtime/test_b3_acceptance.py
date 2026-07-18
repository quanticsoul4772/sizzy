"""B3.9 cut-line acceptance: the four BUILD classes run as a strict-sequential multi-task plan
against a synthetic existing repo, each with its own verifier shape, end to end."""

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
import devharness.verifier.builtin  # noqa: F401  (registers all per-class verifiers)
from devharness.calibration.brier import compute_brier_for_role
from devharness.events.bus import EventBus, verify_chain
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.roles.director import DirectorRole
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.task_lifecycle.done_is_earned import complete
from devharness.verifier.base import VerifierOk
from devharness.verifier.runner import run_verifier

CID = "corr-b3-accept"
# offline-deterministic per-test commands (no network / no nested pytest)
FEATURE_SUITE = ["python", "-B", "-c", "import sys; sys.exit(0 if 'def added' in open('feature.py').read() else 1)"]
BUG_REGRESSION = ["python", "-B", "-c", "import sys; sys.exit(0 if 'return 42' in open('bug.py').read() else 1)"]
REFACTOR_PASSFAIL = ["python", "-B", "run_tests.py"]
BUMP_OK = ["python", "-c", "import sys; sys.exit(0)"]
SUITE_OK = ["python", "-c", "import sys; sys.exit(0)"]
_RUN_TESTS = (
    "import sys\nsys.path.insert(0, '.')\n"
    "try:\n    import refac\n    ok = refac.value() == 7\nexcept Exception:\n    ok = False\n"
    "print('test_value', 'pass' if ok else 'fail')\nprint('test_known_fail', 'fail')\n"
)


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


def _existing_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "feature.py").write_text("# feature target\n")
    (repo / "bug.py").write_text("def foo():\n    return 0\n")  # the bug
    (repo / "refac.py").write_text("def value():\n    return 7\n")
    (repo / "run_tests.py").write_text(_RUN_TESTS)
    (repo / "pyproject.toml").write_text('[project]\ndependencies = ["requests==2.30.0"]\n')
    (repo / "requirements.lock").write_text("requests==2.30.0\n")
    run("add", "-A")
    run("commit", "-m", "base")
    run("branch", "work-base")
    return repo


# per-class write bodies (the developer's change) keyed by task_class
_WRITES = {
    "feature": ("feature.py", "# feature target\ndef added():\n    return 1\n"),
    "bugfix": ("bug.py", "def foo():\n    return 42\n"),
    "refactor": ("refac.py", "def value():\n    result = 7  # refactored\n    return result\n"),
    "dependency_bump": None,  # special-cased: writes manifest + lockfile
}


def _make_complete_task():
    lifecycle = TaskLifecycle()

    async def complete_task(planned_task, developer, conn, event_bus):
        tid, cid, tc = planned_task.task_id, planned_task.correlation_id, planned_task.task_class
        lifecycle.transition(tid, "queued", "running", event_bus, conn)
        wt = developer.worktree.path
        if tc == "feature":
            ctx = {"task_id": tid, "correlation_id": cid, "cwd": wt, "test_command": FEATURE_SUITE,
                   "parallax": _FakeParallax(), "spec_claim": planned_task.spec_claim,
                   "checkpoint": developer.checkpoint,
                   # test_coverage axis (rev 0.3.49): this ctx is hand-built, not derived via
                   # developer._realized_diff(wt), so the qualifying diff must be supplied directly.
                   "diff_content": ("diff --git a/tests/test_feature.py b/tests/test_feature.py\n"
                                     "+++ b/tests/test_feature.py\n+def test_added():\n+    assert True\n")}
        elif tc == "bugfix":
            ctx = {"task_id": tid, "correlation_id": cid, "cwd": wt, "checkpoint": developer.checkpoint,
                   "regression_command": BUG_REGRESSION, "test_command": SUITE_OK}
        elif tc == "refactor":
            ctx = {"task_id": tid, "correlation_id": cid, "cwd": wt, "checkpoint": developer.checkpoint,
                   "pass_fail_command": REFACTOR_PASSFAIL}
        else:  # dependency_bump
            ctx = {"task_id": tid, "correlation_id": cid, "cwd": wt, "checkpoint": developer.checkpoint,
                   "bump_command": BUMP_OK, "test_command": SUITE_OK, "dependency_name": planned_task.dependency_name,
                   "target_version": planned_task.target_version, "manifest_path": planned_task.manifest_path,
                   "lockfile_path": planned_task.lockfile_path}
        result = await run_verifier(planned_task.verifier_ref, ctx, event_bus, conn, lifecycle=lifecycle, checkpoint=developer.checkpoint)
        if isinstance(result, VerifierOk):
            event_bus.emit_sync("reviewer_certified", {"task_id": tid, "reviewer_session_id": "rs", "evidence": {}, "correlation_id": cid, "certified_at_millis": 1}, correlation_id=cid)
            complete(tid, lifecycle, conn, event_bus)

    return complete_task


def _write_hook(planned_task, editor, shell, test_runner):
    tc = planned_task.task_class
    if tc == "dependency_bump":
        editor.write_file("pyproject.toml", '[project]\ndependencies = ["requests==2.31.0"]\n')
        editor.write_file("requirements.lock", "requests==2.31.0\n")
    else:
        path, body = _WRITES[tc]
        editor.write_file(path, body)
        if tc == "feature":
            # test_coverage axis (rev 0.3.49): feature_spec_claim now requires the realized diff to add
            # a new test, or the developer's own acceptance never gets past it.
            editor.write_file("tests/test_feature.py", "def test_added():\n    assert True\n")


class _PerClassDeveloper(DeveloperRole):
    """A developer whose write_hook routes by the dispatched task's class."""

    def __init__(self, **kwargs):
        kwargs["write_hook"] = self._route
        super().__init__(**kwargs)
        self._planned = None

    async def run(self, planned_task, correlation_id):
        self._planned = planned_task
        await super().run(planned_task, correlation_id)

    def _route(self, editor, shell, test_runner):
        _write_hook(self._planned, editor, shell, test_runner)


def _run_acceptance(tmp_path):
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

    # four tasks in a linear dependency chain: feature -> bugfix -> refactor -> dependency_bump
    tasks = [
        {"task_class": "feature", "description": "added() helper",
         "scope_boundary": ["feature.py", "tests/test_feature.py"], "dependencies": []},
        {"task_class": "bugfix", "description": "foo returns 42", "scope_boundary": ["bug.py"], "dependencies": [f"{CID}-t0"], "regression_test_ref": "tests/test_bug.py"},
        {"task_class": "refactor", "description": "restructure value()", "scope_boundary": ["refac.py"], "dependencies": [f"{CID}-t1"]},
        {"task_class": "dependency_bump", "description": "bump requests", "scope_boundary": ["pyproject.toml", "requirements.lock"], "dependencies": [f"{CID}-t2"],
         "dependency_name": "requests", "target_version": "2.31.0", "bump_command": "pip install requests==2.31.0", "manifest_path": "pyproject.toml", "lockfile_path": "requirements.lock"},
    ]
    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    plan_id = asyncio.run(director.run(
        "spec-1", CID, tasks=tasks, developer_role_cls=_PerClassDeveloper, complete_task=_make_complete_task(),
        developer_kwargs={"base_path": str(repo), "base_ref": "work-base", "query_fn": _noop_query()},
    ))
    return conn, registry, plan_id


def test_four_class_multi_task_loop_completes(tmp_path):
    conn, registry, plan_id = _run_acceptance(tmp_path)
    task_ids = [f"{CID}-t{i}" for i in range(4)]

    # strict-sequential: all four tasks completed, plan completed
    assert conn.execute("SELECT current_state, current_task_id FROM proj_plan WHERE plan_id=?", (plan_id,)).fetchone() == ("completed", None)
    states = dict(conn.execute("SELECT task_id, task_state FROM proj_plan_tasks WHERE plan_id=?", (plan_id,)).fetchall())
    assert states == {tid: "completed" for tid in task_ids}

    # each task earned-twice (verifier pass + reviewer cert) with exactly one terminal (Inv 5, 10)
    for tid in task_ids:
        assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (tid,)).fetchone()[0] == "pass"
        assert conn.execute("SELECT verdict FROM proj_reviewer_certs WHERE task_id=?", (tid,)).fetchone()[0] == "certified"
        assert conn.execute("SELECT current_state, outcome FROM proj_task_lifecycle WHERE task_id=?", (tid,)).fetchone() == ("completed", "completed")
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 4

    # the per-class verifiers actually ran (one verifier_outcome per class verifier)
    verifiers = {r[0] for r in conn.execute("SELECT verifier_name FROM proj_verifier_outcomes")}
    assert verifiers == {"feature_spec_claim", "bugfix_regression", "refactor_behavior_preserving", "dependency_resolves"}

    # Inv 7 + Inv 9: valid hash chain + full correlation coverage
    assert verify_chain(conn) == conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert all(r[0] for r in conn.execute("SELECT correlation_id FROM events"))

    # Inv 8: parity over all projections; Inv 18: 24-name boot check
    assert check_projection_rebuild_parity(conn, registry) is True
    assert boot.check_required_gates_registered() is True
    assert len(boot.registered_check_names()) == len(boot.REQUIRED_GATES)
    assert boot.check_terminal_outcome_required_per_task(conn) is True
    assert boot.check_dashboard_tile_coverage() is True


def test_per_class_brier_computed(tmp_path):
    conn, _registry, _plan_id = _run_acceptance(tmp_path)
    # each class made one mutation write that applied -> per-class Brier over its own writes (Inv 14)
    for tc in ("feature", "bugfix", "refactor", "dependency_bump"):
        brier = compute_brier_for_role("developer", tc, conn, min_samples=1)
        assert brier is not None and 0.0 <= brier <= 1.0
    # write events are filtered per class — feature's writes do not bleed into bugfix's metric
    feature_writes = conn.execute("SELECT count(*) FROM proj_developer_activity WHERE event_type='write_applied' AND task_class='feature'").fetchone()[0]
    assert feature_writes >= 1
