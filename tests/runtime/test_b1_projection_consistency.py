"""B1.6: a full read-only-loop event sequence populates all 6 B1 projections."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry

CID = "corr-1"

B1_PROJECTIONS = [
    "proj_questions",
    "proj_assumptions",
    "proj_draft_spec",
    "proj_signed_spec",
    "proj_plan",
    "proj_explore_summary",
]


def test_full_loop_sequence_produces_expected_rows():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry=registry)

    # backing artifacts (the source of truth the handlers read)
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) "
        "VALUES ('spec-1', 'spec', 1, '{}', ?, 10, 0)", (CID,)
    )
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) "
        "VALUES ('plan-1', 'plan', 1, ?, ?, 20, 0)", (json.dumps({"tasks": [{}, {}], "spec_artifact_id": "spec-1"}), CID)
    )
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) "
        "VALUES ('exp-1', 'explore_pass', 1, ?, ?, 30, 0)",
        (json.dumps({"file_tree": [{}, {}, {}], "dependency_manifests": [{}], "test_signatures": [], "ci_configs": [{}], "repo_root": "/repo"}), CID),
    )

    # the synthetic read-only loop
    bus.emit_sync("research_started", {"research_id": CID, "topic": "build a thing"}, correlation_id=CID)
    bus.emit_sync("question_asked", {"research_id": CID, "question_id": "q0", "question_text": "scope?"}, correlation_id=CID)
    bus.emit_sync("question_answered", {"question_id": "q0", "answer_text": "all", "correlation_id": CID, "answered_at_millis": 5}, correlation_id=CID)
    bus.emit_sync("assumption_flagged", {"research_id": CID, "text": "one operator", "confidence": 0.8, "low_confidence_flag": True}, correlation_id=CID)
    bus.emit_sync("spec_drafted", {"spec_id": "spec-1", "title": "spec"}, correlation_id=CID)
    bus.emit_sync("spec_signed", {"spec_id": "spec-1", "signer": "op", "signed_at_millis": 7}, correlation_id=CID)
    bus.emit_sync("plan_drafted", {"plan_id": "plan-1", "spec_id": "spec-1", "task_count": 2}, correlation_id=CID)
    bus.emit_sync("explore_pass_completed", {"repo_path": "/repo", "summary_ref": "exp-1", "file_count": 3, "manifest_count": 1, "test_count": 0, "ci_count": 1}, correlation_id=CID)

    counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in B1_PROJECTIONS}
    assert counts == {t: 1 for t in B1_PROJECTIONS}

    # the question resolved; the draft flipped to signed; counts derived from the explore artifact
    assert conn.execute("SELECT answered FROM proj_questions WHERE question_id='q0'").fetchone()[0] == 1
    assert conn.execute("SELECT low_confidence_flag FROM proj_assumptions").fetchone()[0] == 1
    assert conn.execute("SELECT signed FROM proj_draft_spec WHERE spec_id='spec-1'").fetchone()[0] == 1
    assert conn.execute("SELECT file_count, test_count FROM proj_explore_summary WHERE explore_pass_id='exp-1'").fetchone() == (3, 0)
