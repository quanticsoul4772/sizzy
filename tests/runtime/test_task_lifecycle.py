"""B2.6: task lifecycle transitions + single-terminal enforcement."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.task_lifecycle.base import TaskLifecycle, TaskLifecycleViolation


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn, EventBus(conn), TaskLifecycle()


def test_legal_path_to_completed():
    conn, bus, lifecycle = _setup()
    lifecycle.transition("t1", "queued", "running", bus, conn)
    lifecycle.transition("t1", "running", "awaiting_verifier", bus, conn)
    lifecycle.transition("t1", "awaiting_verifier", "awaiting_review", bus, conn)
    lifecycle.transition("t1", "awaiting_review", "completed", bus, conn)
    assert lifecycle.state("t1") == "completed"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 1


def test_illegal_transition_raises():
    conn, bus, lifecycle = _setup()
    with pytest.raises(TaskLifecycleViolation):
        lifecycle.transition("t1", "queued", "completed", bus, conn)  # queued -> completed is illegal


def test_wrong_from_state_raises():
    conn, bus, lifecycle = _setup()
    lifecycle.transition("t1", "queued", "running", bus, conn)
    with pytest.raises(TaskLifecycleViolation):
        lifecycle.transition("t1", "queued", "running", bus, conn)  # current is running, not queued


def test_second_terminal_raises():
    conn, bus, lifecycle = _setup()
    lifecycle.transition("t1", "queued", "running", bus, conn)
    lifecycle.transition("t1", "running", "aborted", bus, conn)
    with pytest.raises(TaskLifecycleViolation):
        lifecycle.transition("t1", "aborted", "completed", bus, conn)
