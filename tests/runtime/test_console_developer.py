"""Operator console developer action: dispatch the developer to write one plan task.

The console action issues the SAME operations as the ``run_developer`` driver — resolve the
signed spec + plan, select the task, dispatch via ``DirectorRole.dispatch`` -> ``DeveloperRole``,
run verifier-first acceptance + a fresh-context reviewer certification (``completed`` earned
twice, Invariant 5), then ``integrate`` the terminal — and preserves Invariant 1 (the developer
alone takes the single write lock and writes inside its isolated worktree) and the developer
scope boundary (an out-of-scope realized change is rewound + rejected). The console writes no
event store or projection directly; every loop event flows through ``EventBus.emit_sync``.
"""

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console import (
    AllTasksSettled,
    ConsoleDeveloper,
    NoPlan,
    NoSignedSpec,
    UnknownTask,
)
from devharness.console.app import ConsoleApp
from devharness.mcp.base import CallResult
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.task_classes.builtin import register_builtin_task_classes

CID = "proj-dev"
# the worktree "test suite": passes iff app.py declares foo() returning 42
_TEST_CMD = ["python", "-c", "import sys; sys.exit(0 if 'return 42' in open('app.py').read() else 1)"]
_SUPPORTED = "Verdict: **supported** (confidence 1.0, 3/3 passes agree, no refuting findings)."


class _FakeParallax:
    """A parallax client whose verify returns the real rendered `supported` verdict text."""

    def __init__(self, verdict=_SUPPORTED):
        self._verdict = verdict

    async def verify(self, claim, context=""):
        return CallResult(output=self._verdict, cost_usd=0.0, usage=None, is_error=False)


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


def _app():
    return ConsoleApp(db_path=":memory:").connect()


def _seed_spec(conn, *, spec_id="spec-1", signed=1, created_at=100):
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, '{}', ?, ?, ?)",
        (spec_id, CID, created_at, signed),
    )
    conn.commit()
    return spec_id


def _draft_plan(app, tasks, *, spec_id="spec-1"):
    """Draft a real plan artifact via the director console (the operator's prior step)."""
    return app.director().plan(CID, spec_id=spec_id, tasks=tasks, reasoning=_reasoning())


def _feature_task(scope=("app.py", "tests/test_app.py")):
    return {
        "task_class": "feature",
        "description": "foo() returns 42",
        "scope_boundary": list(scope),
        "dependencies": [],
    }


def _dispatch(app, repo, *, write_hook, parallax=None, task_id=None, spec_claim_retries=0):
    return app.developer(base_path=str(repo), test_command=_TEST_CMD).dispatch(
        CID,
        task_id=task_id,
        parallax=parallax or _FakeParallax(),
        developer_kwargs={
            "base_path": str(repo),
            "base_ref": "feature-base",
            "query_fn": _noop_query(),
            "write_hook": write_hook,
        },
        snapshot=False,
        spec_claim_retries=spec_claim_retries,
    )


def _events(conn, event_type):
    return [
        json.loads(p)
        for (p,) in conn.execute(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY seq", (event_type,)
        )
    ]


def test_developer_returns_bound_action():
    assert isinstance(_app().developer(), ConsoleDeveloper)


def test_dispatch_refuses_when_no_signed_spec():
    app = _app()
    _seed_spec(app.conn, signed=0)  # unsigned is not a signed spec to build
    with pytest.raises(NoSignedSpec):
        app.developer().dispatch(CID, parallax=_FakeParallax())


def test_dispatch_refuses_when_no_plan():
    app = _app()
    _seed_spec(app.conn)  # signed spec but the director never drafted a plan
    with pytest.raises(NoPlan):
        app.developer().dispatch(CID, parallax=_FakeParallax())


def test_dispatch_refuses_unknown_task_id():
    app = _app()
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])
    with pytest.raises(UnknownTask):
        app.developer().dispatch(CID, task_id="nope", parallax=_FakeParallax())


def test_dispatch_completes_feature_earned_twice(tmp_path):
    repo = _existing_repo(tmp_path)
    app = _app()
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])

    def write_hook(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)
        editor.write_file("tests/test_app.py", "def test_foo():\n    assert True\n", predicted_success=0.9)

    terminal = _dispatch(app, repo, write_hook=write_hook)
    task_id = f"{CID}-t0"

    assert terminal.outcome == "completed"
    # done earned twice (Invariant 5): the verifier accepted AND the fresh-context reviewer certified
    assert app.conn.execute(
        "SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)
    ).fetchone()[0] == "pass"
    assert app.conn.execute(
        "SELECT verdict FROM proj_reviewer_certs WHERE task_id=?", (task_id,)
    ).fetchone()[0] == "certified"
    assert app.conn.execute(
        "SELECT current_state, outcome FROM proj_task_lifecycle WHERE task_id=?", (task_id,)
    ).fetchone() == ("completed", "completed")


def test_single_writer_lock_taken_and_released(tmp_path):
    repo = _existing_repo(tmp_path)
    app = _app()
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])

    def write_hook(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)

    _dispatch(app, repo, write_hook=write_hook)

    # Invariant 1: exactly one writer took the lock, and it was released (proj_lock empty)
    acquired = _events(app.conn, "write_lock_acquired")
    released = _events(app.conn, "write_lock_released")
    assert len(acquired) == 1 and acquired[0]["holder_role"] == "developer"
    assert len(released) == 1
    assert app.conn.execute("SELECT COUNT(*) FROM proj_lock").fetchone()[0] == 0


def test_developer_writes_inside_isolated_worktree(tmp_path):
    repo = _existing_repo(tmp_path)
    app = _app()
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])

    seen = {}

    def write_hook(editor, shell, test_runner):
        seen["worktree"] = editor.worktree.path
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)

    _dispatch(app, repo, write_hook=write_hook)

    # the developer wrote in an isolated worktree, not the repo checkout itself
    assert seen["worktree"] != str(repo)
    assert ".devharness-worktrees" in seen["worktree"]
    # the repo's own app.py is untouched by the dispatch (the worktree is a sandbox)
    assert (repo / "app.py").read_text() == "def foo():\n    return 0\n"


def test_out_of_scope_realized_change_is_rejected(tmp_path):
    repo = _existing_repo(tmp_path)
    app = _app()
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task(scope=("app.py",))])

    def write_hook(editor, shell, test_runner):
        # a non-editor realized write OUTSIDE the scope boundary — the developer's realized-diff
        # scope enforcement (rev 0.3.21) must catch it and reject, never reaching verify/review
        (Path(shell.worktree.path) / "rogue.py").write_text("x = 1\n")

    terminal = _dispatch(app, repo, write_hook=write_hook)
    task_id = f"{CID}-t0"

    assert terminal.outcome == "rejected"
    assert "scope_violation" in (terminal.reason or terminal.detail or "")
    # the scope-violating task never earned certification
    assert app.conn.execute(
        "SELECT COUNT(*) FROM proj_reviewer_certs WHERE task_id=? AND verdict='certified'", (task_id,)
    ).fetchone()[0] == 0


def test_selects_next_pending_then_settles(tmp_path):
    repo = _existing_repo(tmp_path)
    app = _app()
    _seed_spec(app.conn)
    t0 = dict(_feature_task(), description="task zero")
    t1 = dict(_feature_task(), description="task one")
    _draft_plan(app, [t0, t1])

    def write_hook(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)

    # first dispatch picks the first pending task (t0)
    first = _dispatch(app, repo, write_hook=write_hook)
    assert first.task_id == f"{CID}-t0"
    # second dispatch advances to the next pending task (t1)
    second = _dispatch(app, repo, write_hook=write_hook)
    assert second.task_id == f"{CID}-t1"
    # both settled -> nothing left to dispatch
    with pytest.raises(AllTasksSettled):
        _dispatch(app, repo, write_hook=write_hook)


def test_dispatch_skips_a_rejected_task_and_can_be_explicitly_retried(tmp_path):
    # t0 rejects (test_suite axis fails — no "return 42"); dispatch() with no task_id then picks
    # t1 next, NOT re-picking t0 — the rev-0.3.37 advance-past-any-terminal behavior this plan's
    # console/tui.py fix (rev 0.3.51) makes VISIBLE but deliberately does not change. Then
    # dispatch(task_id=t0) explicitly retries t0.
    repo = _existing_repo(tmp_path)
    app = _app()
    _seed_spec(app.conn)
    t0 = dict(_feature_task(), description="task zero")
    t1 = dict(_feature_task(), description="task one")
    _draft_plan(app, [t0, t1])

    def failing_write_hook(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 0\n", predicted_success=0.9)

    def passing_write_hook(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)
        editor.write_file("tests/test_app.py", "def test_foo():\n    assert True\n", predicted_success=0.9)

    first = _dispatch(app, repo, write_hook=failing_write_hook)
    assert first.task_id == f"{CID}-t0" and first.outcome == "rejected"

    second = _dispatch(app, repo, write_hook=passing_write_hook)  # no task_id -> auto-select
    assert second.task_id == f"{CID}-t1"  # skips past rejected t0, doesn't re-pick it

    retried = _dispatch(app, repo, write_hook=passing_write_hook, task_id=f"{CID}-t0")
    assert retried.task_id == f"{CID}-t0" and retried.outcome == "completed"


@pytest.fixture(autouse=True)
def _task_classes():
    register_builtin_task_classes()
    yield


def _ext_task(tid, deps, correlation_id=CID):
    from types import SimpleNamespace
    return SimpleNamespace(task_id=tid, dependencies=deps, correlation_id=correlation_id)


def _ext_plan(*tasks):
    from types import SimpleNamespace
    return SimpleNamespace(tasks=list(tasks))


def _ext_complete(app, task_id, correlation_id=CID):
    app.writer.emit_sync(
        "terminal_outcome",
        {"task_id": task_id, "outcome": "completed", "detail": "", "reason": "",
         "correlation_id": correlation_id, "terminated_at_millis": 1},
        correlation_id=correlation_id,
    )


def test_external_target_kwargs_scratch_branch_and_chaining():
    # an external target lands the certified change on a per-task devharness/<id> branch, based on
    # whichever task was actually completed most recently in this correlation — a devharness-internal
    # build gets neither.
    from devharness.console.developer import _DEVHARNESS_REPO

    app = _app()
    ext = app.developer(base_path="../proj")

    t0 = _ext_task("t0", [])
    # nothing completed yet in the correlation -> no base_ref (parity with the scaffold's own behavior)
    assert ext._external_target_kwargs(t0, _ext_plan(t0)) == {"scratch_branch": "devharness/t0"}

    _ext_complete(app, "t0")
    t1 = _ext_task("t1", ["t0"])
    assert ext._external_target_kwargs(t1, _ext_plan(t0, t1)) == {
        "scratch_branch": "devharness/t1",
        "base_ref": "devharness/t0",
    }

    _ext_complete(app, "t1")
    # the fan-out regression this fix exists for: t2 ALSO declares dependencies=["t0"] (same shape as
    # t1 — a fan-out sibling, not a chain) -> must chain onto t1 (the actual most-recently-built
    # sibling), NOT "devharness/t0" (what the old dependencies[-1] logic would give).
    t2 = _ext_task("t2", ["t0"])
    plan = _ext_plan(t0, t1, t2)
    assert ext._external_target_kwargs(t2, plan) == {
        "scratch_branch": "devharness/t2",
        "base_ref": "devharness/t1",
    }

    # self-reference / re-drive guard: t1 is a declared descendant of t0, so re-computing kwargs for
    # t0 itself must not chain onto t1's branch (t0 is logically upstream of t1, never the reverse).
    assert "base_ref" not in ext._external_target_kwargs(t0, plan)

    internal = app.developer(base_path=str(_DEVHARNESS_REPO))
    assert internal._external_target_kwargs(t0, plan) == {}


def test_external_target_kwargs_excludes_descendants_on_ancestor_redrive():
    # An operator re-drive of an ALREADY-completed upstream task (DEVHARNESS_TASK_ID targets any
    # task_id) appends a SECOND terminal_outcome for it, at a higher seq than its dependents'. The
    # descendant exclusion must stop that re-drive's own next dispatch from chaining onto a task that
    # depends on it — the bug a naive "latest completed by seq" would have (a later task wrongly
    # basing off something that logically comes before it, backwards).
    app = _app()
    ext = app.developer(base_path="../proj")

    t0 = _ext_task("t0", [])
    t1 = _ext_task("t1", ["t0"])
    plan = _ext_plan(t0, t1)

    _ext_complete(app, "t0")
    _ext_complete(app, "t1")
    _ext_complete(app, "t0")  # re-drive: a second, later terminal_outcome for the same task_id

    # t1 is t0's declared descendant -> excluded regardless of t0's newer terminal's higher seq
    assert "base_ref" not in ext._external_target_kwargs(t0, plan)


class _FlakeyParallax:
    """verify() returns a refuted verdict on the FIRST call, then supported — drives a spec-claim retry."""

    def __init__(self, first, rest=_SUPPORTED):
        self._calls = 0
        self._first, self._rest = first, rest

    async def verify(self, claim, context=""):
        self._calls += 1
        out = self._first if self._calls == 1 else self._rest
        return CallResult(output=out, cost_usd=0.0, usage=None, is_error=False)


def test_spec_claim_retry_recovers_without_lifecycle_crash(tmp_path):
    app = _app()
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])
    repo = _existing_repo(tmp_path)

    def write_hook(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)
        editor.write_file("tests/test_app.py", "def test_foo():\n    assert True\n", predicted_success=0.9)

    refuted = "Verdict: **refuted** (confidence 1.0, the change does not match the claim)."
    terminal = _dispatch(
        app, repo, write_hook=write_hook,
        parallax=_FlakeyParallax(refuted), spec_claim_retries=1,
    )
    # attempt 0's spec-claim deviation must rewind NON-terminally (not terminalize the reused lifecycle);
    # attempt 1 recovers -> completed. Without the terminal_on_fail wiring this raises a lifecycle violation.
    assert terminal.outcome == "completed"


def test_dispatch_splits_verifier_t1_reviewer_frontier(tmp_path, monkeypatch):
    # rev 0.3.84: when no parallax is injected (live), the dispatch builds TWO clients — the
    # first-pass verifier on the cheaper T1 model, the fresh-context reviewer on frontier (the one
    # guaranteed-frontier pass of done-earned-twice). Monkeypatch the live client factory to record
    # the model each was built with; a stubbed developer_kwargs keeps the worker off real SDK.
    from devharness.console import developer as dev_mod
    from devharness.models import model_for_tier

    built = []

    def fake_live(model=None):
        built.append(model)
        return _FakeParallax()

    monkeypatch.setattr(dev_mod, "live_parallax_client", fake_live)
    app = _app()
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])
    repo = _existing_repo(tmp_path)

    def write_hook(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)
        editor.write_file("tests/test_app.py", "def test_foo():\n    assert True\n", predicted_success=0.9)

    app.developer(base_path=str(repo), test_command=_TEST_CMD).dispatch(
        CID, parallax=None,  # None -> the live split builds two clients
        developer_kwargs={"base_path": str(repo), "base_ref": "feature-base",
                          "query_fn": _noop_query(), "write_hook": write_hook},
        snapshot=False,
    )
    # verifier built first (T1 = sonnet), then reviewer (None -> frontier default)
    assert built == [model_for_tier("T1"), None]
    assert built[0] == "claude-sonnet-5"


def test_make_scope_widener_emits_task_scoped_cost(monkeypatch):
    # rev 0.3.71 (run_developer parity): the console dispatch wires a dispatch-time scope widener
    # for external non-OSS targets — its SDK session's realized cost emits task-scoped
    # (role=scope_resolver, SC-6), and the widened files flow back to the developer.
    from devharness.artifacts.plan import PlannedTask
    from devharness.roles import scope_resolver

    app = _app()

    async def fake_resolve(worktree_path, task, *, cost_sink=None, **kw):
        if cost_sink:
            cost_sink(0.07)
        return ["tests/test_cli.py"]

    monkeypatch.setattr(scope_resolver, "resolve_extra_scope", fake_resolve)
    widener = app.developer()._make_scope_widener("c-w")
    task = PlannedTask(task_id="c-w-t0", task_class="dependency_bump", description="bump",
                       scope_boundary=["requirements*.txt"], dependencies=[], correlation_id="c-w")
    extra = asyncio.run(widener("unused-path", task))
    assert extra == ["tests/test_cli.py"]
    spends = [json.loads(p) for (p,) in app.conn.execute(
        "SELECT payload FROM events WHERE event_type='cost_spent'")]
    assert len(spends) == 1
    assert spends[0]["role"] == "scope_resolver"
    assert spends[0]["task_id"] == "c-w-t0"
    assert spends[0]["amount_usd"] == 0.07


def test_dispatch_crash_emits_aborted_terminal_not_silent_loop(tmp_path):
    """A hard crash mid-dispatch (a git-identity/missing-`python`/SDK failure analog) must still
    terminate the task with an ``aborted`` terminal — exactly one (Invariant 10) — not leave it
    pending so the loop silently re-dispatches forever (the 'looping on N' symptom, rev 0.3.86)."""
    app, repo = _app(), _existing_repo(tmp_path)
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])

    def write_hook(editor, shell, test_runner):
        raise RuntimeError("simulated mid-dispatch crash")

    terminal = _dispatch(app, repo, write_hook=write_hook)  # must NOT raise
    assert terminal is not None and terminal.outcome == "aborted", terminal
    assert "simulated mid-dispatch crash" in terminal.reason

    terminals = _events(app.conn, "terminal_outcome")
    assert len(terminals) == 1, terminals            # exactly one terminal (Inv 10)
    assert terminals[0]["outcome"] == "aborted"


def test_dispatch_retries_the_transient_sdk_error(tmp_path):
    """The transient 'error result: success' SDK glitch mid-dispatch is retried (the next attempt cleans
    the worktree and re-dispatches), not aborted — the task completes (rev 0.3.86)."""
    app, repo = _app(), _existing_repo(tmp_path)
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])
    calls = {"n": 0}

    def write_hook(editor, shell, test_runner):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Claude Code returned an error result: success")  # transient, 1st attempt
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)
        editor.write_file("tests/test_app.py", "def test_foo():\n    assert True\n", predicted_success=0.9)

    terminal = _dispatch(app, repo, write_hook=write_hook, spec_claim_retries=1)
    assert calls["n"] == 2                  # retried past the transient
    assert terminal.outcome == "completed"  # then completed, not aborted


def test_scratch_commit_subject_carries_the_task_class():
    # the subject was hardcoded 'feature', so every bugfix/refactor/dependency_bump landed git-labeled
    # as a feature (a prior drive surfaced it) — the subject must carry the task's REAL class.
    from types import SimpleNamespace

    from devharness.console.developer import scratch_commit_subject

    def t(cls, desc="fix the thing"):
        return SimpleNamespace(task_id="c-t0", task_class=cls, description=desc)

    assert scratch_commit_subject(t("bugfix")) == "devharness bugfix c-t0: fix the thing"
    assert scratch_commit_subject(t("refactor")) == "devharness refactor c-t0: fix the thing"
    assert scratch_commit_subject(t("feature")) == "devharness feature c-t0: fix the thing"
    # description is truncated to 60 chars, as before
    assert scratch_commit_subject(t("feature", "x" * 100)).endswith("x" * 60)
    # a class-less task degrades to a neutral label, never "devharness  <id>"
    assert scratch_commit_subject(t("")) == "devharness task c-t0: fix the thing"
    assert scratch_commit_subject(SimpleNamespace(task_id="c-t0", description="d")) == "devharness task c-t0: d"


def test_console_and_script_share_the_scratch_commit_subject():
    # the console/script parity pair (rev 0.3.71's lesson): the script must not re-hardcode the
    # subject — both sites route through the ONE helper.
    from pathlib import Path

    script = (Path(__file__).resolve().parents[2] / "scripts" / "run_developer.py").read_text(encoding="utf-8")
    assert "scratch_commit_subject(planned_task)" in script   # the CALL, not just the import line
    assert 'f"devharness feature' not in script
    console_src = (Path(__file__).resolve().parents[2] / "runtime" / "devharness" / "console"
                   / "developer.py").read_text(encoding="utf-8")
    assert "scratch_commit_subject(planned_task)" in console_src
    assert 'f"devharness feature' not in console_src


# --- §S7 post-build auto-retro (rev 0.4.23) ---

def _auto_retro_dispatch(app, repo, *, retro_engine):
    """Dispatch one completing feature with the production auto_retro posture + an injected engine."""

    def write_hook(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)
        editor.write_file("tests/test_app.py", "def test_foo():\n    assert True\n", predicted_success=0.9)

    return app.developer(base_path=str(repo), test_command=_TEST_CMD,
                         auto_retro=True, retro_engine=retro_engine).dispatch(
        CID, parallax=_FakeParallax(),
        developer_kwargs={"base_path": str(repo), "base_ref": "feature-base",
                          "query_fn": _noop_query(), "write_hook": write_hook},
        snapshot=False, spec_claim_retries=0)


def test_dispatch_auto_retro_drains_terminal_into_spine(tmp_path):
    # rev 0.4.23: a production-surface dispatch (auto_retro=True — the TUI/panel construction posture)
    # drains the learning spine right after the build settles: the terminal gets a retro_run in the
    # SAME store, no separate run_maintenance invocation. The engine is injected (T0-only) — the live
    # path builds the T1 residue engine inside the advisory guard.
    from devharness.retro.engine import RetroEngine

    app = _app()
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])
    repo = _existing_repo(tmp_path)

    terminal = _auto_retro_dispatch(app, repo, retro_engine=RetroEngine(llm_fn=None))
    assert terminal.outcome == "completed"
    runs = _events(app.conn, "retro_run")
    assert [r["source_task_id"] for r in runs] == [terminal.task_id]


def test_dispatch_auto_retro_llm_down_leaves_queue_intact(tmp_path):
    # rev 0.3.57 semantics preserved on the auto path: a down residue LLM halts the drain — the build
    # itself is unaffected (advisory) and NO retro_run is recorded, so the terminal stays queued for
    # the next build / an explicit retro run instead of being consumed as "analyzed, nothing found".
    from devharness.retro.engine import RetroEngine
    from devharness.retro.llm_client import LLMUnavailable

    def down(system, ctx, tier):
        raise LLMUnavailable("transport down")

    app = _app()
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])
    repo = _existing_repo(tmp_path)

    terminal = _auto_retro_dispatch(app, repo, retro_engine=RetroEngine(llm_fn=down))
    assert terminal.outcome == "completed"        # retro must never break a build
    assert _events(app.conn, "retro_run") == []   # the terminal stays queued


def test_dispatch_default_posture_no_auto_retro(tmp_path):
    # auto_retro defaults OFF at the class (the direct-construction/test posture) — only the
    # production surfaces (TUI _developer_surface / panel /dispatch) construct with auto_retro=True.
    app = _app()
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])
    repo = _existing_repo(tmp_path)

    def write_hook(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)
        editor.write_file("tests/test_app.py", "def test_foo():\n    assert True\n", predicted_success=0.9)

    terminal = _dispatch(app, repo, write_hook=write_hook)
    assert terminal.outcome == "completed"
    assert _events(app.conn, "retro_run") == []


def test_run_retro_drain_summary_and_held_reporting():
    # rev 0.4.23: the shared drain reports HELD (fermata: e.g. an orphan running lifecycle row)
    # distinctly from queue-empty, so a permanently-held store is visible, not silent.
    from devharness.console.developer import run_retro_drain
    from devharness.retro.engine import RetroEngine

    app = _app()
    app.writer.emit_sync("terminal_outcome", {"task_id": "t-done", "outcome": "completed", "detail": "",
                         "reason": "", "correlation_id": "c1", "terminated_at_millis": 1},
                         correlation_id="c1")
    r = run_retro_drain(app.conn, app.writer, retro_engine=RetroEngine(llm_fn=None))
    assert r["terminals"] == ["t-done"] and r["held"] is False
    assert r["summary"] == "1 terminal(s) analyzed · 0 signal(s)"

    # an orphan 'running' lifecycle row (started, no terminal) holds the fermata -> HELD, queue intact
    app.writer.emit_sync("terminal_outcome", {"task_id": "t-late", "outcome": "rejected", "detail": "",
                         "reason": "", "correlation_id": "c2", "terminated_at_millis": 2},
                         correlation_id="c2")
    app.writer.emit_sync("task_started", {"task_id": "t-orphan", "role": "developer",
                         "worktree_path": "wt", "started_at_millis": 3, "correlation_id": "c3"},
                         correlation_id="c3")
    r2 = run_retro_drain(app.conn, app.writer, retro_engine=RetroEngine(llm_fn=None))
    assert r2["held"] is True and r2["terminals"] == []
    assert "HELD" in r2["summary"]


def test_run_retro_drain_emits_cost_even_when_drain_raises(monkeypatch):
    # review catch (rev 0.4.23): a mid-drain exception AFTER real T1 spend must not lose the realized
    # cost from the SC-6 ledger — the analyzed terminals' retro_runs exist, so they are never
    # re-analyzed/re-billed and the spend would be unrecoverable. The emission sits in a finally.
    import devharness.retro.llm_client as llm_mod
    from devharness.console import developer as dev_mod
    from devharness.console.developer import run_retro_drain

    class _SpentClient:
        total_cost_usd = 0.33
        model = "claude-sonnet-5"

    def _boom_llm_fn(client):
        def llm(system, ctx, tier):
            raise RuntimeError("mid-analysis crash, NOT LLMUnavailable")
        return llm

    monkeypatch.setattr(dev_mod, "live_parallax_client", lambda model=None: _SpentClient())
    monkeypatch.setattr(llm_mod, "make_llm_fn", _boom_llm_fn)

    app = _app()
    app.writer.emit_sync("terminal_outcome", {"task_id": "t-clean", "outcome": "completed", "detail": "",
                         "reason": "", "correlation_id": "c1", "terminated_at_millis": 1},
                         correlation_id="c1")
    with pytest.raises(RuntimeError):
        run_retro_drain(app.conn, app.writer)  # live path -> clean residue -> boom
    costs = _events(app.conn, "cost_spent")
    assert [c["role"] for c in costs] == ["retro_residue"]
    assert costs[0]["amount_usd"] == 0.33 and costs[0]["correlation_id"] == "maintenance"


def test_run_retro_drain_max_retro_bounds_the_pass():
    # review catch (rev 0.4.23): the post-build auto-drain is BOUNDED (_AUTO_RETRO_MAX) so a first
    # dispatch on a backlog store can't block through the whole backlog inline; the remainder stays
    # queued for the explicit surfaces.
    from devharness.console.developer import run_retro_drain
    from devharness.retro.engine import RetroEngine

    app = _app()
    for n in (1, 2, 3):
        app.writer.emit_sync("terminal_outcome", {"task_id": f"t-{n}", "outcome": "completed",
                             "detail": "", "reason": "", "correlation_id": f"c{n}",
                             "terminated_at_millis": n}, correlation_id=f"c{n}")
    r = run_retro_drain(app.conn, app.writer, retro_engine=RetroEngine(llm_fn=None), max_retro=2)
    assert r["terminals"] == ["t-1", "t-2"]  # bounded; t-3 stays queued
    r2 = run_retro_drain(app.conn, app.writer, retro_engine=RetroEngine(llm_fn=None), max_retro=2)
    assert r2["terminals"] == ["t-3"]


def test_auto_retro_honors_no_llm_env(monkeypatch, tmp_path):
    # review catch (rev 0.4.23): DEVHARNESS_RETRO_NO_LLM is the operator's kill-switch for unattended
    # residue spend — the auto path must drop to the free T0-only engine, never build the live client.
    from devharness.console import developer as dev_mod

    def _never(model=None):
        raise AssertionError("live client must not be built under DEVHARNESS_RETRO_NO_LLM")

    monkeypatch.setattr(dev_mod, "live_parallax_client", _never)
    monkeypatch.setenv("DEVHARNESS_RETRO_NO_LLM", "1")

    app = _app()
    _seed_spec(app.conn)
    _draft_plan(app, [_feature_task()])
    repo = _existing_repo(tmp_path)

    def write_hook(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)
        editor.write_file("tests/test_app.py", "def test_foo():\n    assert True\n", predicted_success=0.9)

    terminal = app.developer(base_path=str(repo), test_command=_TEST_CMD, auto_retro=True).dispatch(
        CID, parallax=_FakeParallax(),
        developer_kwargs={"base_path": str(repo), "base_ref": "feature-base",
                          "query_fn": _noop_query(), "write_hook": write_hook},
        snapshot=False, spec_claim_retries=0)
    assert terminal.outcome == "completed"
    # the drain still ran (llm_fn=None -> the residue layer yields nothing) and the monkeypatched
    # live_parallax_client proves the live T1 client was never built (it raises if called)
    runs = _events(app.conn, "retro_run")
    assert [r["source_task_id"] for r in runs] == [terminal.task_id]
    assert _events(app.conn, "cost_spent") == [] or all(
        c["role"] != "retro_residue" for c in _events(app.conn, "cost_spent"))  # no residue spend
