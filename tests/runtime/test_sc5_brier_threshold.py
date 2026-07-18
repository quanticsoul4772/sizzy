"""B2.8: SC-5 Brier <= 0.15 for calibrated sets, > 0.15 for uncalibrated."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.calibration.brier import compute_brier_for_role
from devharness.calibration.thresholds import SC5_BRIER_THRESHOLD
from devharness.events.bus import EventBus
from devharness.migrate import migrate


def _seed(conn, bus, pairs):
    for i, (predicted, observed) in enumerate(pairs):
        bus.emit_sync("write_attempted", {"task_id": "t1", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "attempted_at_millis": i, "predicted_success": predicted, "task_class": "new_project_scaffold"}, correlation_id="c")
        if observed:
            bus.emit_sync("write_applied", {"task_id": "t1", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "applied_at_millis": i, "observed_success": True, "task_class": "new_project_scaffold"}, correlation_id="c")


def test_threshold_constant_is_single_source():
    assert SC5_BRIER_THRESHOLD == 0.15


def test_calibrated_set_passes_threshold():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    # well-calibrated: confident-and-applied + low-confidence-and-refused
    pairs = [(0.95, True)] * 18 + [(0.05, False)] * 2
    _seed(conn, bus, pairs)
    brier = compute_brier_for_role("developer", "new_project_scaffold", conn, min_samples=20)
    assert brier is not None and brier <= SC5_BRIER_THRESHOLD


def test_miscalibrated_set_exceeds_threshold():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    # confident but the writes were all refused -> badly miscalibrated
    pairs = [(0.9, False)] * 20
    _seed(conn, bus, pairs)
    brier = compute_brier_for_role("developer", "new_project_scaffold", conn, min_samples=20)
    assert brier is not None and brier > SC5_BRIER_THRESHOLD
