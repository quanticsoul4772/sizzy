"""B4.1: migration 0017 — proj_intake_decisions columns + CHECK + indexes; idempotent."""

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


def test_0017_applied():
    assert "0017" in applied_versions(_db())


def test_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_intake_decisions)")}
    assert cols == {"decision_row_id", "intake_correlation_id", "decision", "rejection_reason", "detected_patterns", "correlation_id", "decision_at_millis"}


def test_decision_check_constraint():
    conn = _db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_intake_decisions (intake_correlation_id, decision, correlation_id, decision_at_millis) VALUES ('i', 'maybe', 'c', 1)")


def test_indexes_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_intake_decisions)")}
    assert any("intake" in n for n in indexes) and any("decision" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0017" in applied_versions(conn)
