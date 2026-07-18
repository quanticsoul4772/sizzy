"""B2.6: Invariant 10 — a running task emits exactly one terminal_outcome."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.task_lifecycle.base import TaskLifecycle, TaskLifecycleViolation
from devharness.task_lifecycle.done_is_earned import abort


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn, EventBus(conn), TaskLifecycle()


def test_exactly_one_terminal_per_running_task():
    conn, bus, lifecycle = _setup()
    lifecycle.transition("t1", "queued", "running", bus, conn)
    abort("t1", "budget", lifecycle, conn, bus)
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 1
    # a second terminal transition is refused
    with pytest.raises(TaskLifecycleViolation):
        abort("t1", "again", lifecycle, conn, bus)
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 1


def test_terminal_outcome_carries_outcome_and_reason():
    conn, bus, lifecycle = _setup()
    lifecycle.transition("t1", "queued", "running", bus, conn)
    abort("t1", "lock released without completion", lifecycle, conn, bus)
    import json
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='terminal_outcome'").fetchone()[0])
    assert payload["outcome"] == "aborted"
    assert payload["reason"] == "lock released without completion"
