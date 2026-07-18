"""B4.5: migration 0019 — proj_commit_identity columns + indexes; idempotent."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import applied_versions, migrate


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def test_0019_applied():
    assert "0019" in applied_versions(_db())


def test_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_commit_identity)")}
    assert cols == {"identity_row_id", "oss_task_id", "upstream_repo", "identity_name", "identity_email", "assigned_by", "commit_sha", "correlation_id", "assigned_at_millis"}


def test_indexes_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_commit_identity)")}
    assert any("task" in n for n in indexes) and any("repo" in n for n in indexes) and any("sha" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0019" in applied_versions(conn)
