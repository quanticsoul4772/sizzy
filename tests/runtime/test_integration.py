"""B2.7: integrate() handles completed/rejected/aborted + plan state."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.events.registry import TerminalOutcome
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.integration import integrate


def _setup_plan(task_id="t1", outcome="completed", reason=""):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    bus.emit_sync("plan_drafted", {"plan_id": "p1", "spec_id": "s", "task_count": 1}, correlation_id="c")
    bus.emit_sync("task_started", {"task_id": task_id, "role": "developer", "worktree_path": "/w", "correlation_id": "c", "started_at_millis": 1}, correlation_id="c")
    bus.emit_sync("task_dispatched", {"plan_id": "p1", "task_id": task_id, "dispatched_to_role": "developer", "dispatched_by_role": "director", "correlation_id": "c", "dispatched_at_millis": 2}, correlation_id="c")
    bus.emit_sync("terminal_outcome", {"task_id": task_id, "outcome": outcome, "detail": reason, "reason": reason, "correlation_id": "c", "terminated_at_millis": 9}, correlation_id="c")
    return conn, bus


def test_completed_advances_and_marks_plan_completed():
    conn, bus = _setup_plan(outcome="completed")
    terminal = TerminalOutcome(task_id="t1", outcome="completed", detail="", reason="", correlation_id="c", terminated_at_millis=9)
    assert integrate("p1", "t1", terminal, conn, bus) == "completed"
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id='p1'").fetchone()[0] == "completed"


def test_rejected_blocks_and_emits_abort_decision():
    conn, bus = _setup_plan(outcome="rejected", reason="verifier_failed")
    terminal = TerminalOutcome(task_id="t1", outcome="rejected", detail="verifier_failed", reason="verifier_failed", correlation_id="c", terminated_at_millis=9)
    assert integrate("p1", "t1", terminal, conn, bus) == "blocked"
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id='p1'").fetchone()[0] == "blocked"
    kinds = [json.loads(p[0])["decision_kind"] for p in conn.execute("SELECT payload FROM events WHERE event_type='director_decision'")]
    assert "abort" in kinds


def test_aborted_blocks():
    conn, bus = _setup_plan(outcome="aborted", reason="budget")
    terminal = TerminalOutcome(task_id="t1", outcome="aborted", detail="budget", reason="budget", correlation_id="c", terminated_at_millis=9)
    assert integrate("p1", "t1", terminal, conn, bus) == "blocked"
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id='p1'").fetchone()[0] == "blocked"
