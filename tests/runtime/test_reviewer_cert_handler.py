"""B2.5: reviewer verdict handlers + rebuild parity."""

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


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, registry, EventBus(conn, registry)


def _emit_mixed(bus):
    bus.emit_sync(
        "reviewer_certified",
        {"task_id": "t1", "reviewer_session_id": "s1", "evidence": {"a": 1}, "correlation_id": "c", "certified_at_millis": 5},
        correlation_id="c",
    )
    bus.emit_sync(
        "reviewer_rejected",
        {"task_id": "t2", "reviewer_session_id": "s2", "reason": "tests failed", "evidence": {"b": 2}, "correlation_id": "c", "rejected_at_millis": 6},
        correlation_id="c",
    )


def test_certified_and_rejected_rows():
    conn, _registry, bus = _setup()
    _emit_mixed(bus)
    certified = conn.execute("SELECT task_id, verdict, reason, evidence_json FROM proj_reviewer_certs WHERE task_id='t1'").fetchone()
    assert certified[1] == "certified" and certified[2] is None and json.loads(certified[3]) == {"a": 1}
    rejected = conn.execute("SELECT verdict, reason FROM proj_reviewer_certs WHERE task_id='t2'").fetchone()
    assert rejected == ("rejected", "tests failed")


def test_rebuild_parity_across_mixed_sequence():
    conn, registry, bus = _setup()
    _emit_mixed(bus)
    assert check_projection_rebuild_parity(conn, registry) is True
