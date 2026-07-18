"""Realized-diff OSS content gates (rev 0.3.25, #C1/#C2).

Regression for the audit finding that secret_guard (content axis) and scope_guard (cumulative-LOC)
read context["diff_content"], which the director never populated — so they passed vacuously on every
real OSS contribution. The developer now runs them on the realized worktree diff, in-lock, and a deny
rewinds clean + flags gate_denial.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import PlannedTask
from devharness.checkpoint.base import take_checkpoint
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.worktree.isolate import create_worktree

CID = "corr-content"


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "README.md").write_text("hi\n")
    run("add", "-A")
    run("commit", "-m", "init")
    return repo


def _task(is_oss):
    return PlannedTask(task_id=f"{CID}-t0", task_class="feature", description="x",
                       scope_boundary=["**"], dependencies=[], correlation_id=CID, is_oss=is_oss)


def _developer(tmp_path):
    repo = _git_repo(tmp_path)
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    reg = ProjectionRegistry()
    register_handlers(reg)
    bus = EventBus(conn, reg)
    dev = DeveloperRole.spawn(conn=conn, correlation_id=CID, event_bus=bus, base_path=str(repo))
    wt = create_worktree(f"{CID}-t0", str(repo))
    dev.worktree = wt
    dev.checkpoint = take_checkpoint(f"{CID}-t0", wt.path, CID, bus, conn)
    return dev, wt


def test_oss_secret_in_realized_diff_is_denied_and_rewound(tmp_path):
    dev, wt = _developer(tmp_path)
    (Path(wt.path) / "leak.py").write_text('TOKEN = "-----BEGIN RSA PRIVATE KEY-----"\n')

    dev._enforce_content_gates(_task(is_oss=True), wt, CID)

    assert dev.gate_denial is not None and dev.gate_denial[0] == "secret_guard"
    assert not (Path(wt.path) / "leak.py").exists()  # rewound clean


def test_oss_over_loc_realized_diff_is_denied(tmp_path):
    dev, wt = _developer(tmp_path)
    (Path(wt.path) / "big.py").write_text("x = 1\n" * 600)  # 600 net added LOC > 500 limit

    dev._enforce_content_gates(_task(is_oss=True), wt, CID)

    assert dev.gate_denial is not None and dev.gate_denial[0] == "scope_guard"


def test_clean_oss_diff_passes(tmp_path):
    dev, wt = _developer(tmp_path)
    (Path(wt.path) / "ok.py").write_text("def add(a, b):\n    return a + b\n")

    dev._enforce_content_gates(_task(is_oss=True), wt, CID)

    assert dev.gate_denial is None


def test_oss_workflow_file_in_realized_diff_is_denied(tmp_path):
    # F2: a realized write to a CI/CD workflow file is now caught by workflow_guard on the realized diff
    # (at admission it only saw declared scope globs, never the actual changed paths).
    dev, wt = _developer(tmp_path)
    wf = Path(wt.path) / ".github" / "workflows" / "ci.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("on: push\njobs: {}\n")

    dev._enforce_content_gates(_task(is_oss=True), wt, CID)

    assert dev.gate_denial is not None and dev.gate_denial[0] == "workflow_guard"
    assert not wf.exists()  # rewound clean


def test_oss_empty_realized_diff_fails_closed(tmp_path):
    # F3: an empty / uncomputable realized diff must FAIL CLOSED — an untrusted contribution we cannot
    # inspect must not be admitted (the content gates would otherwise pass vacuously).
    dev, wt = _developer(tmp_path)
    # write nothing -> the realized diff is empty

    dev._enforce_content_gates(_task(is_oss=True), wt, CID)

    assert dev.gate_denial is not None and dev.gate_denial[0] == "content_gates"


def test_non_oss_task_skips_content_gates(tmp_path):
    # the gates are §S5 OSS-only; a non-OSS scaffold with the same content is not screened
    dev, wt = _developer(tmp_path)
    (Path(wt.path) / "leak.py").write_text('TOKEN = "-----BEGIN RSA PRIVATE KEY-----"\n')

    dev._enforce_content_gates(_task(is_oss=False), wt, CID)

    assert dev.gate_denial is None
    assert (Path(wt.path) / "leak.py").exists()  # not rewound — gates did not run
