"""B1.6: 0004 applies cleanly; the 6 B1 projection tables + indexes exist."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import applied_versions, migrate

EXPECTED_COLUMNS = {
    "proj_questions": {"correlation_id", "research_id", "question_id", "question_text", "asked_at_millis", "answered", "answer_text", "answered_at_millis"},
    "proj_assumptions": {"correlation_id", "research_id", "assumption_row_id", "text", "confidence", "low_confidence_flag", "flagged_at_millis"},
    "proj_draft_spec": {"correlation_id", "artifact_id", "spec_id", "signed", "drafted_at_millis"},
    "proj_signed_spec": {"correlation_id", "artifact_id", "spec_id", "signed_by", "signed_at_millis"},
    "proj_plan": {"correlation_id", "plan_id", "spec_artifact_id", "task_count", "drafted_at_millis",
                  "current_state", "executing_task_id", "last_terminal_at_millis", "current_task_id"},  # +B2.7 (0010), +B3.0 (0013)
    "proj_explore_summary": {"correlation_id", "explore_pass_id", "repo_root", "file_count", "manifest_count", "test_count", "ci_count", "completed_at_millis"},
}


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def test_0004_applied():
    assert "0004" in applied_versions(_db())


def test_tables_have_declared_columns():
    conn = _db()
    for table, expected in EXPECTED_COLUMNS.items():
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert cols == expected, table


def test_correlation_id_indexes_present():
    conn = _db()
    for table in EXPECTED_COLUMNS:
        indexes = {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}
        assert any("correlation" in name for name in indexes), table


def test_proj_plan_redefined_with_b1_schema():
    # the B0.4 placeholder (task_id/ordinal/...) is replaced by the real plan projection
    conn = _db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(proj_plan)")}
    assert "plan_id" in cols and "task_count" in cols
    assert "ordinal" not in cols  # old placeholder column gone


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert applied_versions(conn) == ["0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008", "0009", "0010", "0011", "0012", "0013", "0014", "0015", "0016", "0017", "0018", "0019", "0020", "0021", "0022", "0023", "0024", "0025", "0026", "0027", "0028"]
