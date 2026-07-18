"""B5.1: migration 0022 — proj_antibody_queue + proj_gate_change_queue (DROP+CREATE); CHECKs; idempotent."""

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


def test_0022_applied():
    assert "0022" in applied_versions(_db())


def test_antibody_columns_replaced():
    cols = {row[1] for row in _db().execute("PRAGMA table_info(proj_antibody_queue)")}
    assert cols == {"antibody_row_id", "retro_run_correlation_id", "signature_name", "pattern_text",
                    "evidence_event_ids", "source", "review_state", "created_at_millis",
                    "reviewed_by", "reviewed_at_millis"}  # B5.4 added the review columns (0024)
    assert "candidate_id" not in cols  # the B0 placeholder schema is gone


def test_gate_change_columns_and_checks():
    conn = _db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(proj_gate_change_queue)")}
    assert cols == {"gate_change_row_id", "retro_run_correlation_id", "signature_name", "target_gate",
                    "change_kind", "change_details_json", "evidence_event_ids", "source", "review_state",
                    "created_at_millis", "reviewed_by", "reviewed_at_millis"}  # B5.4 added the review columns
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_gate_change_queue (retro_run_correlation_id, target_gate, change_kind, change_details_json, source, created_at_millis) VALUES ('c', 'g', 'bogus', '{}', 't0', 1)")


def test_review_state_default_and_check():
    conn = _db()
    conn.execute("INSERT INTO proj_antibody_queue (retro_run_correlation_id, pattern_text, source, created_at_millis) VALUES ('c', 'p', 't0', 1)")
    assert conn.execute("SELECT review_state FROM proj_antibody_queue").fetchone()[0] == "pending"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_antibody_queue (retro_run_correlation_id, pattern_text, source, review_state, created_at_millis) VALUES ('c', 'p', 't0', 'maybe', 1)")


def test_idempotent_re_run():
    conn = _db()
    assert migrate(conn) == []
    assert "0022" in applied_versions(conn)
