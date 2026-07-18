"""B3.0: migration 0013 — proj_plan column, proj_developer_activity column, proj_plan_tasks, proj_review drop."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import applied_versions, migrate


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def test_0013_applied():
    assert "0013" in applied_versions(_db())


def test_proj_plan_gained_current_task_id():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_plan)")}
    assert "current_task_id" in cols


def test_proj_developer_activity_gained_task_class():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_developer_activity)")}
    assert "task_class" in cols


def test_proj_plan_tasks_declared():
    conn = _db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(proj_plan_tasks)")}
    assert cols == {"plan_id", "task_id", "task_state", "task_class", "dependency_task_ids", "completed_at_millis"}
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(proj_plan_tasks)")}
    assert any("plan" in n for n in indexes) and any("state" in n for n in indexes)


def test_proj_review_dropped():
    tables = {r[0] for r in _db().execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "proj_review" not in tables


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0013" in applied_versions(conn)
