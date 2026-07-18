"""B5.0: migration 0021 — proj_retro_runs columns + CHECK + indexes; idempotent."""

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


def test_0021_applied():
    assert "0021" in applied_versions(_db())


def test_columns():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_retro_runs)")}
    assert cols == {"retro_row_id", "terminal_outcome_correlation_id", "source_task_id", "terminal_kind",
                    "t0_matched_signatures", "llm_invoked", "candidates_emitted_count", "candidate_kinds",
                    "correlation_id", "retro_run_at_millis"}


def test_terminal_kind_check():
    conn = _db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_retro_runs (terminal_outcome_correlation_id, source_task_id, terminal_kind, llm_invoked, candidates_emitted_count, correlation_id, retro_run_at_millis) VALUES ('c', 't', 'failed', 0, 0, 'c', 1)")


def test_indexes_present():
    indexes = {row[1] for row in _db().execute("PRAGMA index_list(proj_retro_runs)")}
    assert any("terminal_corr" in n for n in indexes) and any("task" in n for n in indexes) and any("kind" in n for n in indexes)


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0021" in applied_versions(conn)
