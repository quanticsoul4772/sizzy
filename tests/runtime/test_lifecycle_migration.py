"""B2.6: 0009 applies; columns, CHECK constraint, index present; idempotent."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import applied_versions, migrate


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def test_0009_applied():
    assert "0009" in applied_versions(_db())


def test_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_task_lifecycle)")}
    assert cols == {"task_id", "current_state", "started_at_millis", "terminal_at_millis", "outcome", "reason"}


def test_current_state_check_constraint():
    conn = _db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_task_lifecycle (task_id, current_state) VALUES ('t', 'bogus')")


def test_state_index_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_task_lifecycle)")}
    assert any("state" in name for name in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0009" in applied_versions(conn)
