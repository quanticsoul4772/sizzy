"""B4.1: intake_decision handler inserts proj_intake_decisions; rebuild parity holds."""

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


def _emit(bus):
    bus.emit_sync("intake_decision", {"intake_correlation_id": "i1", "decision": "accepted", "rejection_reason": "", "detected_patterns": [], "decision_at_millis": 5}, correlation_id="c1")
    bus.emit_sync("intake_decision", {"intake_correlation_id": "i2", "decision": "rejected", "rejection_reason": "injection_detected", "detected_patterns": ["markdown_comment", "instruction_override"], "decision_at_millis": 6}, correlation_id="c2")


def test_handler_records_accept_and_reject():
    conn, _registry, bus = _setup()
    _emit(bus)
    accepted = conn.execute("SELECT decision, rejection_reason, detected_patterns FROM proj_intake_decisions WHERE intake_correlation_id='i1'").fetchone()
    assert accepted == ("accepted", None, "[]")
    rejected = conn.execute("SELECT decision, rejection_reason, detected_patterns FROM proj_intake_decisions WHERE intake_correlation_id='i2'").fetchone()
    assert rejected[0] == "rejected" and rejected[1] == "injection_detected"
    assert json.loads(rejected[2]) == ["markdown_comment", "instruction_override"]


def test_rebuild_parity():
    conn, registry, bus = _setup()
    _emit(bus)
    assert check_projection_rebuild_parity(conn, registry) is True
