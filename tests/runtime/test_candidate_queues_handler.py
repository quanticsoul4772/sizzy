"""B5.1: candidate handlers insert into the queues with review_state='pending'; rebuild parity."""

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


def test_handlers_insert_pending():
    conn, _registry, bus = _setup()
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": "c", "signature_name": "sig", "pattern_text": "bad", "evidence_event_ids": ["e1"], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "sig2", "target_gate": "cost_mode_gate", "change_kind": "loosen", "change_details": {"x": 1}, "evidence_event_ids": [], "source": "llm", "created_at_millis": 2}, correlation_id="c")
    assert conn.execute("SELECT pattern_text, source, review_state FROM proj_antibody_queue").fetchone() == ("bad", "t0", "pending")
    assert conn.execute("SELECT target_gate, change_kind, source, review_state FROM proj_gate_change_queue").fetchone() == ("cost_mode_gate", "loosen", "llm", "pending")


def test_rebuild_parity_mixed_sources():
    conn, registry, bus = _setup()
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": "c", "signature_name": "qb", "pattern_text": "q", "evidence_event_ids": [], "source": "quarantine", "created_at_millis": 1}, correlation_id="c")
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "target_gate": "verifier_attached_gate", "change_kind": "tighten", "change_details": {}, "evidence_event_ids": [], "source": "t0", "created_at_millis": 2}, correlation_id="c")
    assert check_projection_rebuild_parity(conn, registry) is True
