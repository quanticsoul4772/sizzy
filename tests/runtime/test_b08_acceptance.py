"""B0.8 end-to-end acceptance: a synthetic sequence of all 7 event types through
the full substrate (emit -> hash chain -> incremental projections -> parity ->
boot check)."""

import sqlite3
import sys
from pathlib import Path

import msgspec
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

from devharness import boot
from devharness.events import registry as ev
from devharness.events.bus import EventBus, verify_chain
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry

# A representative sequence covering all 7 event types (role_transitioned twice).
SEQUENCE = [
    ("connection_opened", ev.ConnectionOpened(connection_id="c1", role="research")),
    ("role_transitioned", ev.RoleTransitioned(from_role="research", to_role="director")),
    ("intent_proposed", ev.IntentProposed(intent_id="i1", call_class="mutation", summary="scaffold")),
    ("gate_fired", ev.GateFired(gate="scope_gate", decision="deny", reason="out of scope", purpose="blast radius", fix="narrow the edit")),
    ("verifier_outcome", ev.VerifierOutcome(task_id="t1", verifier="pytest", passed=True, detail="11 passed")),
    ("checkpoint_taken", ev.CheckpointTaken(task_id="t1", checkpoint_id="cp1", ref="worktree/t1")),
    ("terminal_outcome", ev.TerminalOutcome(task_id="t1", outcome="completed", detail="done")),
    ("role_transitioned", ev.RoleTransitioned(from_role="director", to_role="reviewer")),
]


def _populate(conn: sqlite3.Connection) -> ProjectionRegistry:
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    for event_type, struct in SEQUENCE:
        bus.emit_sync(event_type, msgspec.to_builtins(struct), correlation_id=f"corr-{event_type}")
    return registry


def test_events_land_with_correlation_and_valid_chain():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    _populate(conn)
    rows = conn.execute("SELECT seq, correlation_id, event_type FROM events ORDER BY seq").fetchall()
    assert len(rows) == len(SEQUENCE)
    assert all(r[1] for r in rows), "every event has a correlation_id (Inv 9)"
    assert verify_chain(conn) == len(SEQUENCE), "valid hash chain over the whole log (Inv 7)"


def test_handlers_update_projections_incrementally():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    _populate(conn)
    assert conn.execute("SELECT role FROM proj_role_state WHERE id=1").fetchone()[0] == "reviewer"
    assert conn.execute("SELECT state FROM proj_task_queue WHERE task_id='i1'").fetchone()[0] == "proposed"
    assert conn.execute("SELECT state FROM proj_task_queue WHERE task_id='t1'").fetchone()[0] == "checkpointed"
    # B3.0: proj_review retired; proj_verifier_outcomes is canonical
    assert conn.execute("SELECT outcome FROM proj_verifier_outcomes WHERE task_id='t1'").fetchone()[0] == "pass"
    assert conn.execute("SELECT gate FROM proj_gate_fires").fetchone()[0] == "scope_gate"
    assert conn.execute("SELECT outcome FROM proj_terminal_outcomes WHERE task_id='t1'").fetchone()[0] == "completed"


def test_parity_rebuild_from_scratch_reproduces_state():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = _populate(conn)
    assert check_projection_rebuild_parity(conn, registry) is True


def test_bootcheck_passes_and_fails_closed(monkeypatch):
    assert len(boot.registered_check_names()) == len(boot.REQUIRED_GATES)
    assert boot.check_required_gates_registered() is True
    monkeypatch.setitem(boot.REQUIRED_GATES, "check_absent_name", "C9")
    with pytest.raises(boot.BootError):
        boot.check_required_gates_registered()
