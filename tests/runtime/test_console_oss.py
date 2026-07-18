"""Operator console OSS action: drive the §S5 OSS-contribution path end-to-end.

The console action issues the SAME operations as the ``run_oss`` driver — intake hardening
(cooldown + SPDX license + maintainer verification + injection scan, fail-closed), then on accept
dispatch the ``is_oss`` tasks through the in-lock harness (four §S5 admission gates → fork-branch
worktree → in-lock verifier → bot-identity commit after the verifier passes → fresh-context
reviewer cert), then optionally open the pull request — and preserves the §S5 identity split (the
contribution commit is authored by the bot identity, the pull request by the operator) and
Invariant 1 (the developer alone holds the single write lock and writes inside its isolated
fork-branch worktree). The console writes no event store or projection directly; every loop event
flows through ``EventBus.emit_sync``.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console import ConsoleOss, NoOssTasks, NoSignedSpec
from devharness.console.app import ConsoleApp
from devharness.mcp.base import CallResult
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.oss.maintainer import TestMaintainerVerifier
from devharness.sandbox import registry as sandbox_registry
from devharness.task_classes.builtin import register_builtin_task_classes

CID = "proj-oss"
REPO_SLUG = "octo/widget"
# the worktree "test suite": passes iff feature.py declares the added() helper
_FEATURE_SUITE = ["python", "-c", "import sys; sys.exit(0 if 'def added' in open('feature.py').read() else 1)"]
# a passing parallax rendering — the asterisks keep it clear of the injection-marker phrases the
# feature_spec_claim verifier scans the realized diff for (it is a legitimate verdict, not a directive)
_SUPPORTED = "Verdict: **supported** (confidence 1.0, 3/3 passes agree, no refuting findings)."
_ENV = {"upstream_repo": REPO_SLUG, "license_spdx": "MIT", "requester_id": "alice", "target_branch": "main"}


class _FakeParallax:
    """A parallax client whose verify returns the real rendered passing verdict text."""

    def __init__(self, verdict=_SUPPORTED):
        self._verdict = verdict

    async def verify(self, claim=None, context=""):
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


def _app():
    return ConsoleApp(db_path=":memory:").connect()


def _seed_signed_spec(app, *, spec_id="spec-1"):
    app.conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, '{}', ?, 1, 1)",
        (spec_id, CID),
    )
    app.conn.commit()
    app.writer.emit_sync(
        "spec_signed", {"spec_id": spec_id, "signer": "operator", "signed_at_millis": 1},
        correlation_id=CID,
    )
    return spec_id


def _upstream(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "operator@local")
    run("config", "user.name", "operator")
    run("checkout", "-b", "main")
    (repo / "feature.py").write_text("# target\n")
    run("add", "-A")
    run("commit", "-m", "base")
    return repo


def _oss_task():
    return {
        "task_class": "feature",
        "description": "added() helper",
        "scope_boundary": ["feature.py", "tests/test_feature.py"],
        "dependencies": [],
        "is_oss": True,
        "oss_envelope": dict(_ENV),
    }


def _write_hook(editor, shell, test_runner):
    editor.write_file("feature.py", "# target\ndef added():\n    return 1\n", predicted_success=0.9)
    # test_coverage axis (rev 0.3.49): feature_spec_claim requires the realized diff to add a new test.
    editor.write_file("tests/test_feature.py", "def test_added():\n    assert True\n", predicted_success=0.9)


def _run(app, repo, *, maintainer=(REPO_SLUG, "alice"), tasks=None, parallax=None, publish=False,
         publish_fn=None, write_hook=_write_hook):
    verifier = TestMaintainerVerifier([maintainer]) if maintainer else TestMaintainerVerifier([])
    kwargs = dict(
        tasks=tasks if tasks is not None else [_oss_task()],
        maintainer_verifier=verifier,
        parallax=parallax or _FakeParallax(),
        reasoning=_reasoning(),
        license_fetcher=lambda r: "MIT",
        sandbox_launcher=None,
        developer_kwargs={"base_path": str(repo), "query_fn": _noop_query(), "write_hook": write_hook},
        snapshot=False,
        publish=publish,
    )
    if publish_fn is not None:
        kwargs["publish_fn"] = publish_fn
    return app.oss(base_path=str(repo), test_command=_FEATURE_SUITE).run(CID, **kwargs)


def _events(conn, event_type):
    return [
        json.loads(p)
        for (p,) in conn.execute(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY seq", (event_type,)
        )
    ]


@pytest.fixture(autouse=True)
def _task_classes():
    register_builtin_task_classes()
    yield


@pytest.fixture(autouse=True)
def _wsl(monkeypatch):
    # the §S5 sandbox admission gate fail-closes without a launcher; satisfy it with detected WSL
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: True)
    monkeypatch.setenv("DEVHARNESS_OSS_CAPS_POLL_INTERVAL_SECONDS", "0.001")
    monkeypatch.setenv(
        "DEVHARNESS_OSS_COMMIT_IDENTITIES",
        json.dumps({REPO_SLUG: {"name": "widget-bot", "email": "bot@octo.example"}}),
    )


def test_oss_returns_bound_action():
    assert isinstance(_app().oss(), ConsoleOss)


def test_run_refuses_when_no_signed_spec():
    app = _app()
    with pytest.raises(NoSignedSpec):
        app.oss().run(CID, tasks=[_oss_task()], parallax=_FakeParallax(), reasoning=_reasoning())


def test_run_refuses_when_no_oss_tasks():
    app = _app()
    _seed_signed_spec(app)
    non_oss = {"task_class": "feature", "description": "d", "scope_boundary": ["x"], "dependencies": []}
    with pytest.raises(NoOssTasks):
        app.oss().run(CID, tasks=[non_oss], parallax=_FakeParallax(), reasoning=_reasoning())


def test_intake_rejection_blocks_dispatch(tmp_path):
    repo = _upstream(tmp_path)
    app = _app()
    _seed_signed_spec(app)

    # an unverified maintainer fails the §S5 intake front door -> nothing dispatches
    result = _run(app, repo, maintainer=None)

    assert result["intake"] == "rejected"
    assert result["plan_id"] is None
    # the rejected intake recorded no oss_task_intake (so the director would refuse to plan it)
    assert app.conn.execute("SELECT count(*) FROM proj_oss_intake").fetchone()[0] == 0
    decisions = _events(app.conn, "intake_decision")
    assert decisions[-1]["decision"] == "rejected"
    assert decisions[-1]["rejection_reason"] == "maintainer_unverified"
    # no fork-branch commit was authored
    assert app.conn.execute(
        "SELECT count(*) FROM events WHERE event_type='commit_identity_assigned'"
    ).fetchone()[0] == 0


def test_oss_feature_completes_earned_twice(tmp_path):
    repo = _upstream(tmp_path)
    app = _app()
    _seed_signed_spec(app)

    result = _run(app, repo)
    task_id = f"{CID}-t0"

    assert result["intake"] == "accepted"
    assert result["plan_id"] is not None
    # intake recorded; the loop dispatched the OSS feature
    assert app.conn.execute("SELECT count(*) FROM proj_oss_intake").fetchone()[0] == 1
    # done earned twice (Invariant 5): the in-lock verifier accepted AND the fresh-context reviewer certified
    assert app.conn.execute(
        "SELECT outcome FROM proj_verifier_outcomes WHERE task_id=?", (task_id,)
    ).fetchone()[0] == "pass"
    assert app.conn.execute(
        "SELECT verdict FROM proj_reviewer_certs WHERE task_id=?", (task_id,)
    ).fetchone()[0] == "certified"
    assert app.conn.execute(
        "SELECT current_state, outcome FROM proj_task_lifecycle WHERE task_id=?", (task_id,)
    ).fetchone() == ("completed", "completed")


def test_identity_split_commit_is_the_bot(tmp_path):
    repo = _upstream(tmp_path)
    app = _app()
    _seed_signed_spec(app)

    _run(app, repo)

    # §S5 identity split (commit side): the in-lock contribution commit is authored by the bot
    # identity (DEVHARNESS_OSS_COMMIT_IDENTITIES), assigned only AFTER the verifier passed (B4.5)
    commits = _events(app.conn, "commit_identity_assigned")
    assert len(commits) == 1
    assert commits[0]["oss_task_id"] == f"{CID}-t0"
    assert app.conn.execute("SELECT identity_name FROM proj_commit_identity").fetchone()[0] == "widget-bot"


def test_four_s5_admission_gates_fire(tmp_path):
    repo = _upstream(tmp_path)
    app = _app()
    _seed_signed_spec(app)

    _run(app, repo)

    # the four §S5 fear-map gates admitted the OSS task
    fired = {r[0] for r in app.conn.execute("SELECT gate FROM proj_gate_fires")}
    assert {"workflow_guard", "secret_guard", "scope_guard", "sandbox"} <= fired


def test_single_writer_lock_taken_and_released(tmp_path):
    repo = _upstream(tmp_path)
    app = _app()
    _seed_signed_spec(app)

    _run(app, repo)

    # Invariant 1: exactly one writer took the lock, and it was released (proj_lock empty)
    acquired = _events(app.conn, "write_lock_acquired")
    assert len(acquired) == 1 and acquired[0]["holder_role"] == "developer"
    assert len(_events(app.conn, "write_lock_released")) == 1
    assert app.conn.execute("SELECT COUNT(*) FROM proj_lock").fetchone()[0] == 0


def test_publish_opens_pr_under_operator(tmp_path, monkeypatch):
    repo = _upstream(tmp_path)
    app = _app()
    _seed_signed_spec(app)

    # publish only fires when configured with a push target + operator credential
    monkeypatch.setenv("DEVHARNESS_OSS_PUSH_REPO", "alice/widget")
    monkeypatch.setenv("GH_TOKEN", "tok")

    calls = []

    def fake_publish(**kwargs):
        calls.append(kwargs)
        return {"pr_url": "https://github.com/octo/widget/pull/7", "pr_number": 7,
                "fork_branch": kwargs["fork_branch"]}

    result = _run(app, repo, publish=True, publish_fn=fake_publish)

    # §S5 identity split (PR side): the pull request is opened by the operator (the publish path),
    # separately from the bot-authored commit — only after the contribution was certified+completed
    assert result["published"]["pr_number"] == 7
    assert len(calls) == 1
    assert calls[0]["fork_branch"] == f"devharness-oss/{CID}-t0"
    assert calls[0]["base_branch"] == "main"
    assert calls[0]["upstream_repo"] == REPO_SLUG
    # the commit that the PR carries was the bot's, not the operator's (the split holds)
    assert app.conn.execute("SELECT identity_name FROM proj_commit_identity").fetchone()[0] == "widget-bot"


def test_oss_run_emits_verify_review_cost_when_the_client_spent(tmp_path):
    # rev 0.3.60 (SC-6): the OSS path never routes through ConsoleDeveloper.dispatch, so its
    # verify_review emission never fired here — the run itself now emits the loop-owned client's
    # realized spend. Injected task dicts carry no task_id (the director assigns it), so this is
    # role-scoped; a plan-resolved single task (the live path) gets exact task attribution.
    repo = _upstream(tmp_path)
    app = _app()
    _seed_signed_spec(app)

    costly = _FakeParallax()
    costly.total_cost_usd = 0.37
    _run(app, repo, parallax=costly)

    spends = _events(app.conn, "cost_spent")
    assert len(spends) == 1
    assert spends[0]["role"] == "verify_review"
    assert spends[0]["amount_usd"] == 0.37
    assert spends[0].get("task_id") in (None, "")
    # and the zero-cost stub path stays event-clean (every other test in this file relies on it)
    zero_app = _app()
    _seed_signed_spec(zero_app)
    z = tmp_path / "z"
    z.mkdir()
    _run(zero_app, _upstream(z))
    assert _events(zero_app.conn, "cost_spent") == []


def test_publish_skipped_without_certified_completion(tmp_path, monkeypatch):
    repo = _upstream(tmp_path)
    app = _app()
    _seed_signed_spec(app)

    monkeypatch.setenv("DEVHARNESS_OSS_PUSH_REPO", "alice/widget")
    monkeypatch.setenv("GH_TOKEN", "tok")

    calls = []

    def fake_publish(**kwargs):
        calls.append(kwargs)
        return {}

    # an unverified maintainer rejects intake -> nothing certified -> publish must not fire
    result = _run(app, repo, maintainer=None, publish=True, publish_fn=fake_publish)

    assert result["intake"] == "rejected"
    assert result["published"] is None
    assert calls == []
