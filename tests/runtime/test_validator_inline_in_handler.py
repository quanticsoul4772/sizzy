"""B5.3: the gate_change_candidate persistence path auto-rejects core-gate weakening inline — a
weakening candidate is never observable as 'pending' (it cannot reach operator review)."""

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


def test_weakening_never_pending_after_handler():
    conn, _registry, bus = _setup()
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s",
                  "target_gate": "write_lock_gate", "change_kind": "loosen", "change_details": {},
                  "evidence_event_ids": [], "source": "llm", "created_at_millis": 1}, correlation_id="c")
    # immediately after the emit (handler ran), the candidate is rejected — no pending window
    states = [r[0] for r in conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE target_gate='write_lock_gate'")]
    assert states == ["rejected"]
    # no operator-review API would ever see it as pending
    assert conn.execute("SELECT count(*) FROM proj_gate_change_queue WHERE review_state='pending'").fetchone()[0] == 0


def test_rebuild_parity_with_auto_reject():
    conn, registry, bus = _setup()
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "target_gate": "secret_guard", "change_kind": "loosen", "change_details": {}, "evidence_event_ids": [], "source": "llm", "created_at_millis": 1}, correlation_id="c")  # auto-rejected
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "target_gate": "cost_mode_gate", "change_kind": "loosen", "change_details": {}, "evidence_event_ids": [], "source": "t0", "created_at_millis": 2}, correlation_id="c")  # pending
    # the auto-reject review_state is reproduced from the gate_change_candidate event alone (deterministic)
    assert check_projection_rebuild_parity(conn, registry) is True
    states = dict(conn.execute("SELECT target_gate, review_state FROM proj_gate_change_queue"))
    assert states == {"secret_guard": "rejected", "cost_mode_gate": "pending"}
