"""#H1: the OSS driver runs intake then dispatches only on accept (intake had zero production callers).

drive_oss runs process_intake (cooldown + license + maintainer + injection scan) and dispatches the
OSS task through the real director + the in-lock OSS harness only when intake accepts. A rejected
intake dispatches nothing. No live spend (worker via write_hook, parallax faked, WSL faked).
"""

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime"))
sys.path.insert(0, str(REPO / "scripts"))

import run_oss
from devharness.artifacts.plan import OssEnvelope
from devharness.events.bus import EventBus
from devharness.mcp.base import CallResult
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.oss.maintainer import TestMaintainerVerifier
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.roles.director import DirectorRole
from devharness.sandbox import registry as sandbox_registry
from devharness.task_classes.builtin import register_builtin_task_classes

CID = "oss-test"
REPO_SLUG = "octo/widget"
_CONTENT_SUITE = ["python", "-B", "-c", "import sys; sys.exit(0 if 'def added' in open('feature.py').read() else 1)"]


class _FakeParallax:
    """Discriminating on purpose: it confirms only the C0 diff-grounded claim (which contains the
    'Realized change (unified diff)' preamble), not the bare-claim fallback. So if the reviewer were
    to recompute an EMPTY diff after the bot commit (#8), feature_spec_claim would fall back to the
    bare claim, this returns refuted, and the task would NOT reach completed — guarding the fix."""

    async def verify(self, claim, context=""):  # the realized diff now arrives as the separate context
        supported = "Realized change" in (claim or "") or "Realized change" in (context or "")
        text = ("Verdict: supported (confidence 1.0, no refuting findings)." if supported
                else "Verdict: refuted — no realized diff was provided to verify the claim.")
        return CallResult(output=text, cost_usd=0.0, usage={}, is_error=False)


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


def _oss_write_hook(editor, shell, test_runner):
    editor.write_file("feature.py", "# target\ndef added():\n    return 1\n")
    # test_coverage axis (rev 0.3.49): feature_spec_claim requires the realized diff to add a new test.
    editor.write_file("tests/test_feature.py", "def test_added():\n    assert True\n")


class _OssDeveloper(DeveloperRole):
    def __init__(self, **kwargs):
        kwargs["write_hook"] = _oss_write_hook
        super().__init__(**kwargs)


def _upstream(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "feature.py").write_text("# target\n")
    run("add", "-A")
    run("commit", "-m", "base")
    run("branch", "-M", "main")  # the OSS envelope targets `main`; git init may default to master
    return repo


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: True)
    monkeypatch.setenv("DEVHARNESS_OSS_CAPS_POLL_INTERVAL_SECONDS", "0.001")
    monkeypatch.setenv("DEVHARNESS_OSS_COMMIT_IDENTITIES", json.dumps({REPO_SLUG: {"name": "bot", "email": "b@o.example"}}))
    monkeypatch.setattr(run_oss, "TEST_COMMAND", _CONTENT_SUITE)  # the OSS verifier's test axis (no pytest dir on the fork)

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
    return repo, conn, registry, bus


_ENV = OssEnvelope(upstream_repo=REPO_SLUG, license_spdx="MIT", requester_id="alice", target_branch="main")
_ENV_DICT = {"upstream_repo": REPO_SLUG, "license_spdx": "MIT", "requester_id": "alice", "target_branch": "main"}
_TASKS = [{"task_class": "feature", "description": "added() helper",
           "scope_boundary": ["feature.py", "tests/test_feature.py"],
           "dependencies": [], "is_oss": True, "oss_envelope": dict(_ENV_DICT)}]


def _run(repo, conn, bus, maintainer_verifier):
    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    # rev 0.3.84: verifier + reviewer clients are separate (T1 / frontier); one stub serves both here
    _px = _FakeParallax()
    oss_verify, complete_task = run_oss.build_oss_harness(_px, _px, "spec-1", "plan-1")
    return asyncio.run(run_oss.drive_oss(
        director, signed_spec_id="spec-1", envelope=_ENV, description="add a small helper", tasks=_TASKS,
        maintainer_verifier=maintainer_verifier, license_fetcher=lambda r: _ENV.license_spdx, conn=conn, event_bus=bus, developer_role_cls=_OssDeveloper,
        complete_task=complete_task,
        developer_kwargs={"base_path": str(repo), "query_fn": _noop_query(), "oss_verify_fn": oss_verify},
        intake_correlation_id="intake-0", correlation_id=CID, now_millis=lambda: 1,
    ))


def test_accepted_intake_dispatches_to_completed(tmp_path, monkeypatch):
    repo, conn, registry, bus = _setup(tmp_path, monkeypatch)
    result = _run(repo, conn, bus, TestMaintainerVerifier([(REPO_SLUG, "alice")]))

    assert result["intake"] == "accepted" and result["plan_id"] is not None
    assert conn.execute("SELECT current_state FROM proj_task_lifecycle WHERE task_id=?", (f"{CID}-t0",)).fetchone()[0] == "completed"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='intake_decision' AND json_extract(payload,'$.decision')='accepted'").fetchone()[0] == 1


def test_rejected_intake_dispatches_nothing(tmp_path, monkeypatch):
    repo, conn, registry, bus = _setup(tmp_path, monkeypatch)
    # a maintainer verifier that does NOT know alice -> intake rejects (maintainer_unverified)
    result = _run(repo, conn, bus, TestMaintainerVerifier([]))

    assert result["intake"] == "rejected" and result["plan_id"] is None
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='task_dispatched'").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM artifacts WHERE artifact_type='plan'").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='intake_decision' AND json_extract(payload,'$.decision')='rejected'").fetchone()[0] == 1
