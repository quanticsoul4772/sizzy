"""B2.0: 0005 applies cleanly; proj_lock has the declared columns + index."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import applied_versions, migrate


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def test_0005_applied():
    assert "0005" in applied_versions(_db())


def test_proj_lock_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_lock)")}
    assert cols == {"lock_token", "holder_role", "correlation_id", "acquired_at_millis"}


def test_proj_lock_redefined_from_placeholder():
    # B0.4 placeholder columns (id / event_seq) are gone
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_lock)")}
    assert "id" not in cols and "event_seq" not in cols


def test_holder_index_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_lock)")}
    assert any("holder" in name for name in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert applied_versions(conn) == ["0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008", "0009", "0010", "0011", "0012", "0013", "0014", "0015", "0016", "0017", "0018", "0019", "0020", "0021", "0022", "0023", "0024", "0025", "0026", "0027", "0028"]
