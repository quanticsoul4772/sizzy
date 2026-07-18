"""B2.7: 0010 applies; proj_plan gains columns; proj_task_dispatched + indexes."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import applied_versions, migrate


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def test_0010_applied():
    assert "0010" in applied_versions(_db())


def test_proj_plan_gained_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_plan)")}
    assert {"current_state", "executing_task_id", "last_terminal_at_millis"} <= cols
    # default current_state is 'planned'
    conn = _db()
    conn.execute(
        "INSERT INTO proj_plan (correlation_id, plan_id, spec_artifact_id, task_count, drafted_at_millis) "
        "VALUES ('c', 'p1', 's', 1, 1)"
    )
    assert conn.execute("SELECT current_state FROM proj_plan WHERE plan_id='p1'").fetchone()[0] == "planned"


def test_proj_task_dispatched_columns_and_indexes():
    conn = _db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(proj_task_dispatched)")}
    assert cols == {"task_id", "plan_id", "dispatched_to_role", "dispatched_by_role", "correlation_id", "dispatched_at_millis"}
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(proj_task_dispatched)")}
    assert any("plan" in n for n in indexes) and any("correlation" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0010" in applied_versions(conn)
