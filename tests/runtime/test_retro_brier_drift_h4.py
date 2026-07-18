"""#H4: the retro scheduler carries a live per-class Brier, so calibration_brier_drift can fire.

_build_context always set calibration_snapshot={}, so the _brier_drift T0 predicate (brier > 0.20)
was permanently dead. The scheduler now computes the developer's live per-class Brier from telemetry;
a degraded Brier produces the calibration_brier_drift gate-change candidate (and a well-calibrated /
sample-starved class does not).
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.engine import RetroEngine
from devharness.retro.scheduler import RetroScheduler


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _seed_writes(bus, n, predicted, applied, task_class):
    for i in range(n):
        bus.emit_sync("write_attempted", {"task_id": "w", "worktree_path": "/w", "target_path": f"f{i}.py",
                      "action_kind": "write_file", "correlation_id": "c", "attempted_at_millis": i,
                      "predicted_success": predicted, "task_class": task_class}, correlation_id="c")
        if applied:
            bus.emit_sync("write_applied", {"task_id": "w", "worktree_path": "/w", "target_path": f"f{i}.py",
                          "action_kind": "write_file", "correlation_id": "c", "applied_at_millis": i,
                          "observed_success": True, "task_class": task_class}, correlation_id="c")


def _dispatch_and_terminate(bus, task_id, task_class):
    bus.emit_sync("task_dispatched", {"plan_id": "p", "task_id": task_id, "dispatched_to_role": "developer",
                  "dispatched_by_role": "director", "correlation_id": "c", "dispatched_at_millis": 1,
                  "task_class": task_class, "dependency_task_ids": "[]"}, correlation_id="c")
    bus.emit_sync("terminal_outcome", {"task_id": task_id, "outcome": "completed", "detail": "",
                  "correlation_id": "c", "terminated_at_millis": 2}, correlation_id="c")


def test_degraded_brier_fires_calibration_drift():
    conn, bus = _setup()
    # 20 confident predictions (0.9) that were NOT applied -> observed False -> Brier 0.81 > 0.20
    _seed_writes(bus, 20, predicted=0.9, applied=False, task_class="feature")
    _dispatch_and_terminate(bus, "tf", "feature")

    RetroScheduler(engine=RetroEngine(llm_fn=None)).step(conn, bus, now_millis=lambda: 5)

    sigs = json.loads(conn.execute("SELECT t0_matched_signatures FROM proj_retro_runs WHERE source_task_id='tf'").fetchone()[0])
    assert "calibration_brier_drift" in sigs
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='gate_change_candidate' "
                        "AND json_extract(payload,'$.signature_name')='calibration_brier_drift'").fetchone()[0] == 1


def test_well_calibrated_does_not_fire_drift():
    conn, bus = _setup()
    # 20 confident predictions that WERE applied -> Brier 0.01 <= 0.20
    _seed_writes(bus, 20, predicted=0.9, applied=True, task_class="feature")
    _dispatch_and_terminate(bus, "tf", "feature")

    RetroScheduler(engine=RetroEngine(llm_fn=None)).step(conn, bus, now_millis=lambda: 5)

    sigs = json.loads(conn.execute("SELECT t0_matched_signatures FROM proj_retro_runs WHERE source_task_id='tf'").fetchone()[0])
    assert "calibration_brier_drift" not in sigs


def test_sample_starved_class_does_not_fire_drift():
    conn, bus = _setup()
    _seed_writes(bus, 3, predicted=0.9, applied=False, task_class="feature")  # < min_samples -> no live Brier
    _dispatch_and_terminate(bus, "tf", "feature")

    RetroScheduler(engine=RetroEngine(llm_fn=None)).step(conn, bus, now_millis=lambda: 5)

    sigs = json.loads(conn.execute("SELECT t0_matched_signatures FROM proj_retro_runs WHERE source_task_id='tf'").fetchone()[0])
    assert "calibration_brier_drift" not in sigs
