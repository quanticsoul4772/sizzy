"""B2.8: Invariant 14 (full) — CALL_CLASSES source-of-truth + Brier metric over it."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.calibration.brier import _is_mutation, compute_brier, compute_brier_for_role
from devharness.call_class import CALL_CLASSES, classify
from devharness.events.bus import EventBus
from devharness.migrate import migrate


def test_call_classes_single_source_of_truth():
    assert CALL_CLASSES == frozenset({"mutation", "read", "harness"})
    assert classify("Write") == "mutation" and classify("Read") == "read"


def test_brier_filter_derives_from_call_classes():
    # the metric's mutation filter and any role prompt's enumeration both go through classify()
    assert _is_mutation("write_file") is True
    assert _is_mutation("append_to_file") is True
    assert _is_mutation("open_file") is False  # read action is not counted
    assert _is_mutation("run_tests") is False


def test_brier_metric_finite_over_sample():
    assert 0.0 <= compute_brier([(0.9, True), (0.2, False)]) <= 1.0


def test_brier_aggregates_over_event_log():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    for i in range(5):
        bus.emit_sync("write_attempted", {"task_id": "t1", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "attempted_at_millis": i, "predicted_success": 0.7, "task_class": "new_project_scaffold"}, correlation_id="c")
        bus.emit_sync("write_applied", {"task_id": "t1", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "applied_at_millis": i, "observed_success": True, "task_class": "new_project_scaffold"}, correlation_id="c")
    value = compute_brier_for_role("developer", "new_project_scaffold", conn, min_samples=1)
    assert value is not None and 0.0 <= value <= 1.0
