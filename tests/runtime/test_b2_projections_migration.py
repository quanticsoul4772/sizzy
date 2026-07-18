"""B2.9: 0012 applies; the 2 new tables have columns, CHECK, indexes; idempotent."""

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


def test_0012_applied():
    assert "0012" in applied_versions(_db())


def test_developer_activity_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_developer_activity)")}
    assert cols == {
        "activity_row_id", "task_id", "event_type", "correlation_id", "target_path",
        "action_kind", "predicted_success", "observed_success", "event_at_millis", "task_class",
    }


def test_verifier_outcomes_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_verifier_outcomes)")}
    assert cols == {"outcome_row_id", "task_id", "verifier_name", "outcome", "evidence_json", "correlation_id", "outcome_at_millis"}


def test_check_constraints():
    conn = _db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_developer_activity (task_id, event_type, correlation_id, event_at_millis) VALUES ('t', 'nope', 'c', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_verifier_outcomes (task_id, verifier_name, outcome, correlation_id, outcome_at_millis) VALUES ('t', 'v', 'maybe', 'c', 1)")


def test_indexes_present():
    conn = _db()
    for table in ("proj_developer_activity", "proj_verifier_outcomes"):
        indexes = {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}
        assert any("task" in n for n in indexes) and any("correlation" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0012" in applied_versions(conn)
