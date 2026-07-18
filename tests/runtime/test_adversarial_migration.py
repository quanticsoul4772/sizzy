"""B3.7: migration 0015 — proj_adversarial columns, CHECK, indexes; idempotent."""

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


def test_0015_applied():
    assert "0015" in applied_versions(_db())


def test_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_adversarial)")}
    assert cols == {"adversarial_row_id", "probe_name", "target_gate", "outcome", "regression_reason", "correlation_id", "run_at_millis"}


def test_outcome_check_constraint():
    conn = _db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_adversarial (probe_name, target_gate, outcome, correlation_id, run_at_millis) VALUES ('p', 'g', 'bogus', 'c', 1)")


def test_indexes_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_adversarial)")}
    assert any("gate" in n for n in indexes) and any("outcome" in n for n in indexes) and any("correlation" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0015" in applied_versions(conn)
