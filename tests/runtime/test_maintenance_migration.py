"""B3.6: migration 0014 — proj_maintenance columns, CHECKs, indexes; idempotent."""

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


def test_0014_applied():
    assert "0014" in applied_versions(_db())


def test_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_maintenance)")}
    assert cols == {"maintenance_row_id", "cycle_kind", "event_kind", "action_description", "correlation_id", "event_at_millis"}


def test_check_constraints():
    conn = _db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_maintenance (cycle_kind, event_kind, correlation_id, event_at_millis) VALUES ('nope', 'tick', 'c', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_maintenance (cycle_kind, event_kind, correlation_id, event_at_millis) VALUES ('audit', 'bogus', 'c', 1)")


def test_indexes_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_maintenance)")}
    assert any("cycle" in n for n in indexes) and any("correlation" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0014" in applied_versions(conn)
