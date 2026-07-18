"""B2.9: the 5 write-phase handler extensions update their projections; parity holds."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, registry, EventBus(conn, registry)


def _full(bus):
    bus.emit_sync("plan_drafted", {"plan_id": "p1", "spec_id": "s", "task_count": 1}, correlation_id="c")
    bus.emit_sync("task_dispatched", {"plan_id": "p1", "task_id": "t1", "dispatched_to_role": "developer", "dispatched_by_role": "director", "correlation_id": "c", "dispatched_at_millis": 1}, correlation_id="c")
    bus.emit_sync("task_started", {"task_id": "t1", "role": "developer", "worktree_path": "/w", "correlation_id": "c", "started_at_millis": 2}, correlation_id="c")
    bus.emit_sync("write_attempted", {"task_id": "t1", "worktree_path": "/w", "target_path": "src/a.py", "action_kind": "write_file", "correlation_id": "c", "attempted_at_millis": 3, "predicted_success": 0.9}, correlation_id="c")
    bus.emit_sync("write_applied", {"task_id": "t1", "worktree_path": "/w", "target_path": "src/a.py", "action_kind": "write_file", "correlation_id": "c", "applied_at_millis": 4, "observed_success": True}, correlation_id="c")
    bus.emit_sync("verifier_outcome", {"task_id": "t1", "verifier": "test_suite", "passed": True, "detail": "", "evidence": {"n": 11}}, correlation_id="c")


def test_developer_activity_rows():
    conn, _registry, bus = _setup()
    _full(bus)
    kinds = [r[0] for r in conn.execute("SELECT event_type FROM proj_developer_activity ORDER BY activity_row_id")]
    assert kinds == ["task_dispatched", "task_started", "write_attempted", "write_applied"]
    attempt = conn.execute("SELECT predicted_success FROM proj_developer_activity WHERE event_type='write_attempted'").fetchone()[0]
    assert attempt == 0.9
    applied = conn.execute("SELECT observed_success FROM proj_developer_activity WHERE event_type='write_applied'").fetchone()[0]
    assert applied == 1


def test_verifier_outcomes_row():
    conn, _registry, bus = _setup()
    _full(bus)
    row = conn.execute("SELECT verifier_name, outcome, evidence_json FROM proj_verifier_outcomes WHERE task_id='t1'").fetchone()
    assert row[0] == "test_suite" and row[1] == "pass" and "11" in row[2]


def test_rebuild_parity():
    conn, registry, bus = _setup()
    _full(bus)
    assert check_projection_rebuild_parity(conn, registry) is True
