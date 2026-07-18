"""B1.6: each B1 event updates its projection on emit; rebuild parity holds."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry

CID = "corr-1"


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry=registry)
    return conn, registry, bus


def _insert_artifact(conn, artifact_id, artifact_type, payload, created):
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) "
        "VALUES (?, ?, 1, ?, ?, ?, 0)",
        (artifact_id, artifact_type, json.dumps(payload), CID, created),
    )


def _full_sequence(conn, bus):
    _insert_artifact(conn, "spec-1", "spec", {}, 111)
    _insert_artifact(conn, "plan-1", "plan", {"tasks": [{}, {}, {}], "spec_artifact_id": "spec-1"}, 222)
    _insert_artifact(
        conn, "exp-1", "explore_pass",
        {"file_tree": [{}, {}], "dependency_manifests": [{}], "test_signatures": [{}], "ci_configs": [{}], "repo_root": "/r"},
        333,
    )
    bus.emit_sync("question_asked", {"research_id": CID, "question_id": "q0", "question_text": "scope?"}, correlation_id=CID)
    bus.emit_sync("question_answered", {"question_id": "q0", "answer_text": "whole repo", "correlation_id": CID, "answered_at_millis": 50}, correlation_id=CID)
    bus.emit_sync("assumption_flagged", {"research_id": CID, "text": "single operator", "confidence": 0.9, "low_confidence_flag": False}, correlation_id=CID)
    bus.emit_sync("spec_drafted", {"spec_id": "spec-1", "title": "the spec"}, correlation_id=CID)
    bus.emit_sync("spec_signed", {"spec_id": "spec-1", "signer": "alice", "signed_at_millis": 60}, correlation_id=CID)
    bus.emit_sync("plan_drafted", {"plan_id": "plan-1", "spec_id": "spec-1", "task_count": 3}, correlation_id=CID)
    bus.emit_sync("explore_pass_completed", {"repo_path": "/r", "summary_ref": "exp-1", "file_count": 2, "manifest_count": 1, "test_count": 1, "ci_count": 1}, correlation_id=CID)


def test_each_b1_event_updates_its_projection():
    conn, _registry, bus = _setup()
    _full_sequence(conn, bus)

    assert conn.execute(
        "SELECT question_text, answered, answer_text, answered_at_millis FROM proj_questions WHERE question_id='q0'"
    ).fetchone() == ("scope?", 1, "whole repo", 50)
    assert conn.execute("SELECT text, confidence, low_confidence_flag FROM proj_assumptions").fetchone() == ("single operator", 0.9, 0)
    assert conn.execute("SELECT signed, drafted_at_millis FROM proj_draft_spec WHERE spec_id='spec-1'").fetchone() == (1, 111)
    assert conn.execute("SELECT signed_by, signed_at_millis FROM proj_signed_spec WHERE spec_id='spec-1'").fetchone() == ("alice", 60)
    assert conn.execute("SELECT spec_artifact_id, task_count, drafted_at_millis FROM proj_plan WHERE plan_id='plan-1'").fetchone() == ("spec-1", 3, 222)
    assert conn.execute(
        "SELECT repo_root, file_count, manifest_count, test_count, ci_count, completed_at_millis FROM proj_explore_summary WHERE explore_pass_id='exp-1'"
    ).fetchone() == ("/r", 2, 1, 1, 1, 333)


def test_rebuild_parity_reproduces_incremental_state():
    conn, registry, bus = _setup()
    _full_sequence(conn, bus)
    assert check_projection_rebuild_parity(conn, registry) is True
