"""0027 issue-discovery substrate: a work_item_candidate event lands in proj_work_item_queue."""

import sqlite3
import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.events.registry import WorkItemCandidate
from devharness.migrate import applied_versions, migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def _bus(conn):
    reg = ProjectionRegistry()
    register_handlers(reg)
    return EventBus(conn, reg)


def test_0027_applied():
    assert "0027" in applied_versions(_db())


def test_work_item_candidate_lands_in_queue():
    conn = _db()
    bus = _bus(conn)
    payload = msgspec.to_builtins(WorkItemCandidate(
        correlation_id="disc-1", candidate_id="disc-1-w0", title="Add X",
        description="Add an X to the CLI", rationale="users need X", kind="feature",
        scope_hint=["src/**"], target_repo="C:/repo", source="llm", created_at_millis=7,
    ))
    bus.emit_sync("work_item_candidate", payload, correlation_id="disc-1")

    rows = conn.execute(
        "SELECT candidate_id, title, kind, target_repo, source, scope_hint FROM proj_work_item_queue"
    ).fetchall()
    assert rows == [("disc-1-w0", "Add X", "feature", "C:/repo", "llm", '["src/**"]')]


def test_empty_description_rejected():
    import pytest
    with pytest.raises(ValueError):
        WorkItemCandidate(
            correlation_id="d", candidate_id="d-w0", title="t", description="", rationale="r",
            kind="feature", scope_hint=[], target_repo="r", source="llm", created_at_millis=1,
        )
