"""B4.6: requester cooldowns — rate-limit triggers a future cooldown; check_cooldown honors it."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.oss.cooldowns import CooldownConfig, check_cooldown, check_intake_rate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry

CFG = CooldownConfig(max_intakes_per_window=3, window_seconds=3600, cooldown_duration_seconds=1800)


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _intake(bus, requester, at):
    bus.emit_sync("oss_task_intake", {"upstream_repo": "octo/widget", "license_spdx": "MIT", "requester_id": requester, "target_branch": "main", "intake_at_millis": at}, correlation_id="c")


def test_config_env_override(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_COOLDOWN_MAX_INTAKES", "5")
    monkeypatch.setenv("DEVHARNESS_OSS_COOLDOWN_WINDOW_SECONDS", "60")
    monkeypatch.setenv("DEVHARNESS_OSS_COOLDOWN_DURATION_SECONDS", "120")
    cfg = CooldownConfig.from_env()
    assert cfg.max_intakes_per_window == 5 and cfg.window_seconds == 60 and cfg.cooldown_duration_seconds == 120


def test_under_threshold_no_cooldown():
    conn, bus = _setup()
    _intake(bus, "r1", 1000)
    _intake(bus, "r1", 2000)
    r = check_intake_rate("r1", conn, CFG, bus, "c", now_millis_fn=lambda: 3000)
    assert r.triggered_cooldown is False and r.count == 2
    assert check_cooldown("r1", conn, lambda: 3000).active is False


def test_threshold_trips_cooldown():
    conn, bus = _setup()
    for i in range(3):
        _intake(bus, "r1", 1000 + i)
    r = check_intake_rate("r1", conn, CFG, bus, "c", now_millis_fn=lambda: 2000)
    assert r.triggered_cooldown is True and r.count == 3
    # a future cooldown_until_millis was written + budget_exceeded(oss_requester_cooldown) emitted
    until = conn.execute("SELECT cooldown_until_millis FROM proj_requester_cooldown WHERE requester_id='r1'").fetchone()[0]
    assert until == 2000 + 1800 * 1000
    cd = check_cooldown("r1", conn, lambda: 2000)
    assert cd.active is True and cd.cooldown_until_millis == until
    assert conn.execute("SELECT count(*) FROM proj_budget_exceeded WHERE budget_kind='oss_requester_cooldown'").fetchone()[0] == 1


def test_cooldown_expires():
    conn, bus = _setup()
    for i in range(3):
        _intake(bus, "r1", 1000 + i)
    check_intake_rate("r1", conn, CFG, bus, "c", now_millis_fn=lambda: 2000)
    after = 2000 + 1800 * 1000 + 1
    assert check_cooldown("r1", conn, lambda: after).active is False  # past the cooldown window


def test_window_excludes_old_intakes():
    conn, bus = _setup()
    _intake(bus, "r1", 1)  # far outside the window
    _intake(bus, "r1", 5_000_000)
    _intake(bus, "r1", 5_000_001)
    # window is 3600s = 3_600_000ms; now=5_000_002 -> window_start=1_400_002; the at=1 intake is excluded
    r = check_intake_rate("r1", conn, CFG, bus, "c", now_millis_fn=lambda: 5_000_002)
    assert r.count == 2 and r.triggered_cooldown is False
