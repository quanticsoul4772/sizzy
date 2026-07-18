"""B4.5 ordering fix: the OSS bot-identity commit fires only AFTER the verifier passes.

VerifierOk -> commit_identity_assigned fires; VerifierFailed -> no commit; non-OSS -> the developer
never commits (the verifier reads the uncommitted tree in the existing complete_task path).
"""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import OssEnvelope, PlannedTask
from devharness.events.bus import EventBus
from devharness.lock.base import SingleWriterLock
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.verifier.base import VerifierFailed, VerifierOk

REPO = "octo/widget"


def _setup(tmp_path):
    import sqlite3
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
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return repo, conn, EventBus(conn, registry)


def _oss_task():
    return PlannedTask(task_id="t1", task_class="feature", description="d", scope_boundary=["feature.py"],
                       dependencies=[], correlation_id="c", verifier_ref="feature_spec_claim", is_oss=True,
                       oss_envelope=OssEnvelope(upstream_repo=REPO, license_spdx="MIT", requester_id="alice", target_branch="main"))


def _developer(repo, conn, bus, oss_verify_fn):
    def write_hook(editor, shell, test_runner):
        editor.write_file("feature.py", "# target\ndef added(): return 1\n")
    return DeveloperRole(event_bus=bus, conn=conn, context={}, base_path=str(repo), lock=SingleWriterLock(),
                         write_hook=write_hook, oss_verify_fn=oss_verify_fn, now_millis=lambda: 1,
                         query_fn=_noop_query())


def _noop_query():
    async def q(*, prompt, options):
        if False:
            yield None
    return q


def test_commit_fires_after_verifier_ok(tmp_path):
    repo, conn, bus = _setup(tmp_path)

    async def verify_ok(planned_task, developer, conn, event_bus):
        return VerifierOk(name="feature_spec_claim", evidence={})

    dev = _developer(repo, conn, bus, verify_ok)
    asyncio.run(dev.run(_oss_task(), "c"))
    assert isinstance(dev.oss_verify_result, VerifierOk)
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='commit_identity_assigned'").fetchone()[0] == 1


def test_no_commit_on_verifier_failed(tmp_path):
    repo, conn, bus = _setup(tmp_path)

    async def verify_fail(planned_task, developer, conn, event_bus):
        return VerifierFailed(name="feature_spec_claim", reason="claim not met", evidence={})

    dev = _developer(repo, conn, bus, verify_fail)
    asyncio.run(dev.run(_oss_task(), "c"))
    assert isinstance(dev.oss_verify_result, VerifierFailed)
    # the fork-branch never received an identity commit
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='commit_identity_assigned'").fetchone()[0] == 0


def test_non_oss_developer_does_not_commit(tmp_path):
    repo, conn, bus = _setup(tmp_path)
    task = PlannedTask(task_id="t2", task_class="feature", description="d", scope_boundary=["feature.py"],
                       dependencies=[], correlation_id="c", verifier_ref="feature_spec_claim")  # is_oss defaults False
    dev = _developer(repo, conn, bus, oss_verify_fn=None)
    asyncio.run(dev.run(task, "c"))
    assert dev.oss_verify_result is None
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='commit_identity_assigned'").fetchone()[0] == 0
