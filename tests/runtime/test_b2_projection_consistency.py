"""B2.9: a synthetic B2 e2e sequence populates the write-phase projections."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def test_b2_sequence_produces_expected_rows():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)

    bus.emit_sync("plan_drafted", {"plan_id": "p1", "spec_id": "s", "task_count": 1}, correlation_id="c")
    bus.emit_sync("task_dispatched", {"plan_id": "p1", "task_id": "t1", "dispatched_to_role": "developer", "dispatched_by_role": "director", "correlation_id": "c", "dispatched_at_millis": 1}, correlation_id="c")
    bus.emit_sync("task_started", {"task_id": "t1", "role": "developer", "worktree_path": "/w", "correlation_id": "c", "started_at_millis": 2}, correlation_id="c")
    for i in range(2):
        bus.emit_sync("write_attempted", {"task_id": "t1", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "attempted_at_millis": 3 + i, "predicted_success": 0.8}, correlation_id="c")
        bus.emit_sync("write_applied", {"task_id": "t1", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "applied_at_millis": 3 + i, "observed_success": True}, correlation_id="c")
    bus.emit_sync("verifier_outcome", {"task_id": "t1", "verifier": "parallax_verify", "passed": False, "detail": "x", "evidence": {}}, correlation_id="c")

    # developer activity: 1 dispatched + 1 started + 2 attempted + 2 applied = 6
    assert conn.execute("SELECT count(*) FROM proj_developer_activity").fetchone()[0] == 6
    assert conn.execute("SELECT count(*) FROM proj_developer_activity WHERE event_type='write_applied'").fetchone()[0] == 2
    # one verifier outcome, fail
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id='t1'").fetchone()[0] == "fail"
