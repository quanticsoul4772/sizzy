"""B4.6: per-task caps — wall_clock + USD, env override, deterministic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.oss.caps import CapConfig, check_caps_during_dispatch


# elapsed is computed from started_at_millis vs now_millis_fn; e.g. start=0, now=N*1000 -> N seconds
def _caps(task_id, elapsed_seconds, cost, cfg):
    return check_caps_during_dispatch(task_id, 0, cost, cfg, now_millis_fn=lambda: int(elapsed_seconds * 1000))


def test_under_limits_not_exceeded():
    cfg = CapConfig(wall_clock_seconds=100, max_usd_cost=5.0)
    assert _caps("t", 50, 2.0, cfg).exceeded is False


def test_wall_clock_exceeded():
    cfg = CapConfig(wall_clock_seconds=100, max_usd_cost=5.0)
    r = _caps("t", 101, 0.0, cfg)
    assert r.exceeded is True and r.kind == "oss_wall_clock"
    assert r.observed == 101 and r.limit == 100


def test_usd_exceeded():
    cfg = CapConfig(wall_clock_seconds=100, max_usd_cost=5.0)
    r = _caps("t", 10, 5.5, cfg)
    assert r.exceeded is True and r.kind == "oss_usd"
    assert r.observed == 5.5 and r.limit == 5.0


def test_wall_clock_checked_first():
    cfg = CapConfig(wall_clock_seconds=100, max_usd_cost=5.0)
    assert _caps("t", 200, 99.0, cfg).kind == "oss_wall_clock"  # both over -> wall_clock wins


def test_env_override(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_CAP_WALL_CLOCK_SECONDS", "10")
    monkeypatch.setenv("DEVHARNESS_OSS_CAP_USD", "1.0")
    cfg = CapConfig.from_env()
    assert cfg.wall_clock_seconds == 10 and cfg.max_usd_cost == 1.0
    # no explicit cap_config -> from_env() picks up the override
    assert check_caps_during_dispatch("t", 0, 0.0, now_millis_fn=lambda: 11_000).exceeded is True
