"""B2.5: 0008 applies; columns, CHECK constraint, indexes present; idempotent."""

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


def test_0008_applied():
    assert "0008" in applied_versions(_db())


def test_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_reviewer_certs)")}
    assert cols == {
        "cert_row_id", "task_id", "reviewer_session_id", "verdict", "reason",
        "evidence_json", "correlation_id", "verdict_at_millis",
    }


def test_verdict_check_constraint():
    conn = _db()
    # an invalid verdict is rejected by the CHECK constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO proj_reviewer_certs (task_id, reviewer_session_id, verdict, correlation_id, verdict_at_millis) "
            "VALUES ('t', 's', 'maybe', 'c', 1)"
        )


def test_indexes_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_reviewer_certs)")}
    assert any("task" in n for n in indexes) and any("correlation" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0008" in applied_versions(conn)
