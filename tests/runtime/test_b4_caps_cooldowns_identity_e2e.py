"""B4.8 acceptance: caps + cooldowns + revocation + commit-identity exercised end to end."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.checkpoint.base import take_checkpoint
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.oss.caps import CapConfig, enforce_caps
from devharness.oss.commit_identity import commit_with_identity, get_commit_identity
from devharness.oss.cooldowns import CooldownConfig, check_cooldown, check_intake_rate
from devharness.oss.revocation import revoke_requester
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.worktree.isolate import create_worktree, discard_worktree

REPO = "octo/widget"
CFG = CooldownConfig(max_intakes_per_window=2, window_seconds=3600, cooldown_duration_seconds=1800)


def _setup():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_wall_clock_cap_aborts():
    conn, bus = _setup()
    cfg = CapConfig(wall_clock_seconds=100, max_usd_cost=5.0)
    r = enforce_caps("t1", 0, 0.0, bus, "c", cap_config=cfg, now_millis_fn=lambda: 200_000)  # 200s > 100s
    assert r.exceeded and r.kind == "oss_wall_clock"
    assert conn.execute("SELECT budget_kind, action_taken FROM proj_budget_exceeded WHERE subject_id='t1'").fetchone() == ("oss_wall_clock", "abort")


def test_usd_cap_aborts():
    conn, bus = _setup()
    cfg = CapConfig(wall_clock_seconds=100, max_usd_cost=5.0)
    enforce_caps("t2", 0, 9.0, bus, "c", cap_config=cfg, now_millis_fn=lambda: 1000)
    assert conn.execute("SELECT budget_kind FROM proj_budget_exceeded WHERE subject_id='t2'").fetchone()[0] == "oss_usd"


def test_rate_limit_cooldown_then_revocation():
    conn, bus = _setup()
    for i in range(2):
        bus.emit_sync("oss_task_intake", {"upstream_repo": REPO, "license_spdx": "MIT", "requester_id": "r1", "target_branch": "main", "intake_at_millis": 1000 + i}, correlation_id="c")
    res = check_intake_rate("r1", conn, CFG, bus, "c", now_millis_fn=lambda: 2000)
    assert res.triggered_cooldown is True
    row = conn.execute("SELECT triggered_by FROM proj_requester_cooldown WHERE requester_id='r1'").fetchone()
    assert row[0] == "rate_limit"
    # revocation: a different requester is denied indefinitely
    revoke_requester("r2", "abuse", "operator", conn, bus, "c", now_millis_fn=lambda: 1000)
    assert conn.execute("SELECT budget_kind, reason FROM proj_budget_exceeded WHERE subject_id='r2'").fetchone() == ("requester_revoked", "abuse")
    far_future = 1000 + 50 * 365 * 24 * 60 * 60 * 1000
    assert check_cooldown("r2", conn, lambda: far_future).active is True


def _repo(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "operator@local")
    run("config", "user.name", "operator")
    run("checkout", "-b", "main")
    (repo / "x.py").write_text("x\n")
    run("add", "-A")
    run("commit", "-m", "base")
    return repo


def test_oss_commit_identity_vs_default(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("DEVHARNESS_OSS_COMMIT_IDENTITIES", json.dumps({REPO: {"name": "widget-bot", "email": "bot@octo.example"}}))
    repo = _repo(tmp_path)
    conn, bus = _setup()
    # OSS commit -> configured bot identity (author AND committer)
    wt = create_worktree("oss-i", str(repo), oss_task_id="oss-i", oss_target_branch="main")
    try:
        (Path(wt.path) / "feature.py").write_text("def added(): return 1\n")
        identity = get_commit_identity(REPO, "feature")
        commit_with_identity(wt.path, "OSS contribution", identity, oss_task_id="oss-i", upstream_repo=REPO,
                             event_bus=bus, correlation_id="c", now_millis=lambda: 5)
        g = lambda *a: subprocess.run(["git", "-C", wt.path, *a], capture_output=True, text=True).stdout.strip()
        assert g("log", "-1", "--format=%an") == "widget-bot" and g("log", "-1", "--format=%cn") == "widget-bot"
        assert conn.execute("SELECT identity_name FROM proj_commit_identity").fetchone()[0] == "widget-bot"
    finally:
        discard_worktree(wt)
        subprocess.run(["git", "-C", str(repo), "branch", "-D", "devharness-oss/oss-i"], capture_output=True)

    # a non-OSS checkpoint commit keeps the repo's default operator identity (unchanged from B2.3)
    subprocess.run(["git", "-C", str(repo), "checkout", "main"], check=True, capture_output=True)
    wt2 = create_worktree("plain-i", str(repo))
    try:
        (Path(wt2.path) / "y.py").write_text("y\n")
        take_checkpoint("plain-i", wt2.path, "c2", bus, conn, now_millis=lambda: 6)
        g2 = lambda *a: subprocess.run(["git", "-C", wt2.path, *a], capture_output=True, text=True).stdout.strip()
        assert g2("log", "-1", "--format=%an") == "operator"
    finally:
        discard_worktree(wt2)
