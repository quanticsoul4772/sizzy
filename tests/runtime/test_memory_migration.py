"""B5.5: migration 0025 — proj_memory columns + UNIQUE entry_id + indexes; idempotent."""

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


def test_0025_applied():
    assert "0025" in applied_versions(_db())


def test_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_memory)")}
    assert cols == {"memory_row_id", "entry_id", "entry_type", "entry_payload_json", "source_project",
                    "verified_locally", "created_at_millis", "verified_at_millis", "verifier_evidence_json", "correlation_id"}


def test_entry_id_unique():
    conn = _db()
    conn.execute("INSERT INTO proj_memory (entry_id, entry_type, entry_payload_json, source_project, created_at_millis, correlation_id) VALUES ('e', 'antibody', '{}', 'p', 1, 'c')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_memory (entry_id, entry_type, entry_payload_json, source_project, created_at_millis, correlation_id) VALUES ('e', 'antibody', '{}', 'p', 2, 'c')")


def test_indexes_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_memory)")}
    assert any("source" in n for n in indexes) and any("verified" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0025" in applied_versions(conn)
