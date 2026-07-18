"""B2.6: C2 terminal-outcome boot-check passes clean, fails closed on silent termination."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.migrate import migrate


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def test_registered_under_c2():
    assert "check_terminal_outcome_required_per_task" in boot.registered_check_names()
    assert boot.REQUIRED_GATES["check_terminal_outcome_required_per_task"] == "C2"


def test_passes_on_fresh_db():
    assert boot.check_terminal_outcome_required_per_task() is True


def test_passes_running_and_terminal_tasks():
    conn = _db()
    conn.execute("INSERT INTO proj_task_lifecycle (task_id, current_state, started_at_millis) VALUES ('t1', 'running', 1)")
    conn.execute(
        "INSERT INTO proj_task_lifecycle (task_id, current_state, started_at_millis, terminal_at_millis, outcome) "
        "VALUES ('t2', 'completed', 1, 9, 'completed')"
    )
    conn.commit()
    assert boot.check_terminal_outcome_required_per_task(conn) is True


def test_fails_closed_on_silent_termination():
    conn = _db()
    # started, not running, no terminal -> silently terminated
    conn.execute("INSERT INTO proj_task_lifecycle (task_id, current_state, started_at_millis) VALUES ('t1', 'awaiting_review', 1)")
    conn.commit()
    with pytest.raises(boot.BootError):
        boot.check_terminal_outcome_required_per_task(conn)
