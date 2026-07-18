"""B2.8: Brier metric — compute_brier + compute_brier_for_role."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.calibration.brier import compute_brier, compute_brier_for_role
from devharness.events.bus import EventBus
from devharness.migrate import migrate


def test_compute_brier_known_values():
    # perfect predictions -> 0
    assert compute_brier([(1.0, True), (0.0, False)]) == 0.0
    # worst predictions -> 1
    assert compute_brier([(0.0, True), (1.0, False)]) == 1.0
    # 0.5 on everything -> 0.25
    assert compute_brier([(0.5, True), (0.5, False)]) == 0.25


def test_compute_brier_empty_raises():
    with pytest.raises(ValueError):
        compute_brier([])


def _seed(conn, bus, n, predicted, observed):
    for i in range(n):
        bus.emit_sync("write_attempted", {"task_id": "t1", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "attempted_at_millis": i, "predicted_success": predicted, "task_class": "new_project_scaffold"}, correlation_id="c")
        if observed:
            bus.emit_sync("write_applied", {"task_id": "t1", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "applied_at_millis": i, "observed_success": True, "task_class": "new_project_scaffold"}, correlation_id="c")


def test_aggregates_pairs_from_events():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    _seed(conn, bus, 10, predicted=0.9, observed=True)  # confident + applied -> low brier
    value = compute_brier_for_role("developer", "new_project_scaffold", conn, min_samples=5)
    assert value is not None
    assert abs(value - (0.1 ** 2)) < 1e-9  # each pair (0.9, True) -> (0.9-1)^2 = 0.01


def test_returns_none_below_min_samples():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    _seed(conn, bus, 3, predicted=0.9, observed=True)
    assert compute_brier_for_role("developer", "new_project_scaffold", conn, min_samples=20) is None


def test_refused_writes_count_as_observed_false():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    # confident predictions but the writes were refused (no write_applied) -> high brier
    _seed(conn, bus, 5, predicted=0.9, observed=False)
    value = compute_brier_for_role("developer", "new_project_scaffold", conn, min_samples=1)
    assert abs(value - (0.9 ** 2)) < 1e-9  # (0.9 - 0)^2 = 0.81
