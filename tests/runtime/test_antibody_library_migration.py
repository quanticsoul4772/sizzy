"""B5.2: migration 0023 — proj_antibody_library columns + pattern_text CHECK + indexes; idempotent."""

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


def test_0023_applied():
    assert "0023" in applied_versions(_db())


def test_columns_no_code_field():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_antibody_library)")}
    assert cols == {"antibody_row_id", "pattern_text", "source_candidate_id", "added_by",
                    "added_at_millis", "revoked_at_millis", "revoke_reason", "correlation_id"}
    # Inv 11: pattern_text is the only non-metadata column; no callable/code/eval column
    assert not any(h in c for c in cols for h in ("callable", "code", "eval", "exec"))


def test_pattern_text_check():
    conn = _db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_antibody_library (antibody_row_id, pattern_text, source_candidate_id, added_by, added_at_millis, correlation_id) VALUES (1, '', 'c', 'op', 1, 'c')")


def test_indexes_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_antibody_library)")}
    assert any("source" in n for n in indexes) and any("revoked" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0023" in applied_versions(conn)
