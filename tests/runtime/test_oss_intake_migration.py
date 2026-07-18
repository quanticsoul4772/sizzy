"""B4.0: migration 0016 — proj_oss_intake columns + indexes; idempotent."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import applied_versions, migrate


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def test_0016_applied():
    assert "0016" in applied_versions(_db())


def test_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_oss_intake)")}
    assert cols == {"intake_row_id", "upstream_repo", "license_spdx", "requester_id", "target_branch", "correlation_id", "intake_at_millis"}


def test_indexes_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_oss_intake)")}
    assert any("repo" in n for n in indexes) and any("requester" in n for n in indexes) and any("correlation" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0016" in applied_versions(conn)
