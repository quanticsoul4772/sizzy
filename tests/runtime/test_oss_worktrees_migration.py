"""B4.4: migration 0018 — proj_oss_worktrees columns + indexes; idempotent."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import applied_versions, migrate


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def test_0018_applied():
    assert "0018" in applied_versions(_db())


def test_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_oss_worktrees)")}
    assert cols == {"worktree_row_id", "oss_task_id", "upstream_repo", "target_branch", "fork_branch", "worktree_path", "correlation_id", "created_at_millis"}


def test_indexes_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_oss_worktrees)")}
    assert any("task" in n for n in indexes) and any("repo" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0018" in applied_versions(conn)
