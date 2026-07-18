"""B1.1: 0003_artifacts migration applies cleanly through the forward-only runner."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import applied_versions, migrate


def test_0003_applies_and_records_in_ledger():
    conn = sqlite3.connect(":memory:")
    migrate(conn)  # 0001 + 0002 + 0003
    assert "0003" in applied_versions(conn)


def test_artifacts_table_columns():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)")}
    assert cols == {
        "artifact_id",
        "artifact_type",
        "schema_version",
        "payload_json",
        "correlation_id",
        "created_at_millis",
        "signed",
    }


def test_artifacts_indexes_present():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(artifacts)")}
    assert "idx_artifacts_type" in indexes
    assert "idx_artifacts_correlation" in indexes


def test_runner_idempotent_respecting_ledger():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    # second run applies nothing (ledger already records all)
    assert migrate(conn) == []
    assert applied_versions(conn) == ["0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008", "0009", "0010", "0011", "0012", "0013", "0014", "0015", "0016", "0017", "0018", "0019", "0020", "0021", "0022", "0023", "0024", "0025", "0026", "0027", "0028"]
