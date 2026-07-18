"""B2.8: 0011 applies; columns + indexes present; idempotent."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import applied_versions, migrate


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def test_0011_applied():
    assert "0011" in applied_versions(_db())


def test_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_trust_grants)")}
    assert cols == {
        "grant_row_id", "role_name", "task_class", "brier_at_grant", "granted_at_millis",
        "expires_at_millis", "revoked_at_millis", "granted_by",
    }


def test_indexes_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_trust_grants)")}
    assert any("role_class" in n for n in indexes) and any("expires" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0011" in applied_versions(conn)
