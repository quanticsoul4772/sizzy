"""B2.6: Invariant 5 — a completed terminal is earned twice (verification + certification)."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.task_lifecycle.done_is_earned import DoneNotEarned, complete


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    lifecycle = TaskLifecycle()
    lifecycle.transition("t1", "queued", "running", bus, conn)
    return conn, bus, lifecycle


def test_completed_requires_both_halves():
    conn, bus, lifecycle = _setup()
    # neither half present
    with pytest.raises(DoneNotEarned):
        complete("t1", lifecycle, conn, bus)
    # verifier pass only
    bus.emit_sync("verifier_outcome", {"task_id": "t1", "verifier": "v", "passed": True, "detail": "", "evidence": {}}, correlation_id="c")
    with pytest.raises(DoneNotEarned):
        complete("t1", lifecycle, conn, bus)
    # plus reviewer cert -> earned
    bus.emit_sync("reviewer_certified", {"task_id": "t1", "reviewer_session_id": "s", "evidence": {}, "correlation_id": "c", "certified_at_millis": 1}, correlation_id="c")
    complete("t1", lifecycle, conn, bus)
    assert lifecycle.state("t1") == "completed"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 1
