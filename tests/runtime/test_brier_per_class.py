"""B3.0: per-task-class Brier filtering — one class's writes do not bleed into another's metric."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.calibration.brier import compute_brier_for_role
from devharness.events.bus import EventBus
from devharness.migrate import migrate


def _seed(bus, n, predicted, observed, task_class, offset=0):
    for i in range(offset, offset + n):
        bus.emit_sync("write_attempted", {"task_id": f"{task_class}-t", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "attempted_at_millis": i, "predicted_success": predicted, "task_class": task_class}, correlation_id="c")
        if observed:
            bus.emit_sync("write_applied", {"task_id": f"{task_class}-t", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "applied_at_millis": i, "observed_success": True, "task_class": task_class}, correlation_id="c")


def test_filters_by_task_class():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    # feature: confident + applied -> low Brier (0.01); bugfix: confident + refused -> high Brier (0.81)
    _seed(bus, 5, predicted=0.9, observed=True, task_class="feature", offset=0)
    _seed(bus, 5, predicted=0.9, observed=False, task_class="bugfix", offset=100)

    feature = compute_brier_for_role("developer", "feature", conn, min_samples=1)
    bugfix = compute_brier_for_role("developer", "bugfix", conn, min_samples=1)

    assert abs(feature - 0.01) < 1e-9  # only feature's (0.9, True) pairs
    assert abs(bugfix - 0.81) < 1e-9   # only bugfix's (0.9, False) pairs — no bleed from feature


def test_other_class_does_not_satisfy_min_samples():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    _seed(bus, 3, predicted=0.9, observed=True, task_class="feature")
    # refactor has zero writes -> below min_samples -> None even though feature has writes
    assert compute_brier_for_role("developer", "refactor", conn, min_samples=1) is None
    assert compute_brier_for_role("developer", "feature", conn, min_samples=1) is not None
