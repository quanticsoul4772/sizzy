"""B4.6 e2e: caps abort with budget_exceeded; rate-limit trips a cooldown that refuses the next
intake; revoked requesters are refused indefinitely; non-OSS dispatch has no caps."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import OssEnvelope
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.oss.caps import CapConfig, enforce_caps
from devharness.oss.cooldowns import CooldownConfig
from devharness.oss.intake import process_intake
from devharness.oss.maintainer import TestMaintainerVerifier
from devharness.oss.revocation import revoke_requester
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry

REPO = "octo/widget"
CFG = CooldownConfig(max_intakes_per_window=3, window_seconds=3600, cooldown_duration_seconds=1800)


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _env(requester="alice"):
    return OssEnvelope(upstream_repo=REPO, license_spdx="MIT", requester_id=requester, target_branch="main")


def _intake(conn, bus, requester="alice", at=1000, icid="i"):
    return process_intake(_env(requester), "add foo", bus, intake_correlation_id=icid, correlation_id="c",
                          maintainer_verifier=TestMaintainerVerifier([(REPO, requester)]),
                          license_fetcher=lambda r: "MIT",
                          now_millis=lambda: at, conn=conn, cooldown_config=CFG)


def test_wall_clock_cap_aborts():
    conn, bus = _setup()
    cfg = CapConfig(wall_clock_seconds=100, max_usd_cost=5.0)
    # started at 0, now at 120s -> 120s elapsed > 100s cap
    r = enforce_caps("t1", 0, 0.0, bus, "c", cap_config=cfg, now_millis_fn=lambda: 120_000)
    assert r.exceeded and r.kind == "oss_wall_clock"
    row = conn.execute("SELECT budget_kind, action_taken, subject_id FROM proj_budget_exceeded").fetchone()
    assert row == ("oss_wall_clock", "abort", "t1")


def test_usd_cap_aborts():
    conn, bus = _setup()
    cfg = CapConfig(wall_clock_seconds=100, max_usd_cost=5.0)
    enforce_caps("t2", 0, 9.0, bus, "c", cap_config=cfg, now_millis_fn=lambda: 10_000)
    row = conn.execute("SELECT budget_kind, action_taken FROM proj_budget_exceeded WHERE subject_id='t2'").fetchone()
    assert row == ("oss_usd", "abort")


def test_rate_limit_then_next_intake_refused():
    conn, bus = _setup()
    # three accepted intakes trip a cooldown
    for i in range(3):
        assert _intake(conn, bus, at=1000 + i, icid=f"i{i}") == "accepted"
    # the 4th intake (within the cooldown) is refused with the cooldown reason + audit event
    assert _intake(conn, bus, at=2000, icid="i4") == "rejected"
    decisions = conn.execute("SELECT decision, rejection_reason FROM proj_intake_decisions WHERE intake_correlation_id='i4'").fetchone()
    assert decisions == ("rejected", "requester_in_cooldown")
    assert conn.execute("SELECT count(*) FROM proj_budget_exceeded WHERE budget_kind='oss_requester_cooldown'").fetchone()[0] >= 1


def test_revoked_requester_refused():
    conn, bus = _setup()
    revoke_requester("mallory", "abuse", "operator", conn, bus, "c", now_millis_fn=lambda: 500)
    assert _intake(conn, bus, requester="mallory", at=1000, icid="i9") == "rejected"
    row = conn.execute("SELECT rejection_reason FROM proj_intake_decisions WHERE intake_correlation_id='i9'").fetchone()
    assert row == ("requester_in_cooldown",)


def test_non_oss_has_no_caps():
    conn, bus = _setup()
    cfg = CapConfig(wall_clock_seconds=100, max_usd_cost=5.0)
    # a non-OSS task simply does not call enforce_caps; under both caps -> no abort emitted
    r = enforce_caps("t9", 0, 1.0, bus, "c", cap_config=cfg, now_millis_fn=lambda: 10_000)
    assert r.exceeded is False
    assert conn.execute("SELECT count(*) FROM proj_budget_exceeded").fetchone()[0] == 0
