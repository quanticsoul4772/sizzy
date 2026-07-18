"""B4.6: migration 0020 — proj_requester_cooldown + proj_budget_exceeded columns/CHECKs/indexes."""

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


def test_0020_applied():
    assert "0020" in applied_versions(_db())


def test_cooldown_columns_and_check():
    conn = _db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(proj_requester_cooldown)")}
    assert cols == {"cooldown_row_id", "requester_id", "cooldown_until_millis", "triggered_by", "trigger_reason", "correlation_id", "triggered_at_millis"}
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_requester_cooldown (requester_id, cooldown_until_millis, triggered_by, correlation_id, triggered_at_millis) VALUES ('r', 1, 'bogus', 'c', 1)")


def test_budget_columns_and_checks():
    conn = _db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(proj_budget_exceeded)")}
    assert cols == {"budget_row_id", "budget_kind", "limit_value", "observed_value", "action_taken", "subject_id", "reason", "correlation_id", "exceeded_at_millis"}
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_budget_exceeded (budget_kind, action_taken, subject_id, correlation_id, exceeded_at_millis) VALUES ('reasoning', 'abort', 's', 'c', 1)")  # B2.x kind not in CHECK


def test_indexes_present():
    conn = _db()
    cd = {row[1] for row in conn.execute("PRAGMA index_list(proj_requester_cooldown)")}
    be = {row[1] for row in conn.execute("PRAGMA index_list(proj_budget_exceeded)")}
    assert any("requester" in n for n in cd) and any("until" in n for n in cd)
    assert any("kind" in n for n in be) and any("subject" in n for n in be)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0020" in applied_versions(conn)
