"""B0.5 tests: on-emit incremental handlers, parity, and the 24-name boot registry."""

import sqlite3
import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.migrate import migrate
from devharness.events.bus import EventBus
from devharness.events import registry as ev
from devharness.projections.registry import ProjectionRegistry
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity


def _wired():
    conn = sqlite3.connect(":memory:")
    migrate(conn)  # 0001 + 0002
    reg = ProjectionRegistry()
    register_handlers(reg)
    return conn, EventBus(conn, reg), reg


def _emit(bus, event_type, struct):
    bus.emit_sync(event_type, msgspec.to_builtins(struct), correlation_id="corr-1")


def test_each_handler_updates_its_projection_on_emit():
    conn, bus, _ = _wired()
    _emit(bus, "connection_opened", ev.ConnectionOpened(connection_id="x", role="research"))
    assert conn.execute("SELECT role FROM proj_role_state WHERE id=1").fetchone()[0] == "research"

    _emit(bus, "role_transitioned", ev.RoleTransitioned(from_role="research", to_role="director"))
    assert conn.execute("SELECT role FROM proj_role_state WHERE id=1").fetchone()[0] == "director"

    _emit(bus, "intent_proposed", ev.IntentProposed(intent_id="i1", call_class="mutation", summary="s"))
    assert conn.execute("SELECT task_class, state FROM proj_task_queue WHERE task_id='i1'").fetchone() == ("mutation", "proposed")

    _emit(bus, "gate_fired", ev.GateFired(gate="scope_gate", decision="deny", reason="r", purpose="p", fix="f"))
    assert conn.execute("SELECT gate, decision FROM proj_gate_fires").fetchone() == ("scope_gate", "deny")

    _emit(bus, "verifier_outcome", ev.VerifierOutcome(task_id="t1", verifier="pytest", passed=True, detail="d"))
    # B3.0: proj_review retired; proj_verifier_outcomes is the canonical verifier landing point
    assert conn.execute("SELECT verifier_name, outcome FROM proj_verifier_outcomes WHERE task_id='t1'").fetchone() == ("pytest", "pass")

    _emit(bus, "checkpoint_taken", ev.CheckpointTaken(task_id="t1", checkpoint_id="cp1", ref="ref"))
    assert conn.execute("SELECT state FROM proj_task_queue WHERE task_id='t1'").fetchone()[0] == "checkpointed"

    _emit(bus, "terminal_outcome", ev.TerminalOutcome(task_id="t1", outcome="completed", detail="d"))
    assert conn.execute("SELECT outcome FROM proj_terminal_outcomes WHERE task_id='t1'").fetchone()[0] == "completed"


def test_parity_incremental_equals_rebuild_multi_event():
    conn, bus, reg = _wired()
    sequence = [
        ("connection_opened", ev.ConnectionOpened(connection_id="x", role="research")),
        ("role_transitioned", ev.RoleTransitioned(from_role="research", to_role="director")),
        ("intent_proposed", ev.IntentProposed(intent_id="i1", call_class="read", summary="s")),
        ("gate_fired", ev.GateFired(gate="g", decision="allow", reason="r", purpose="p", fix="f")),
        ("verifier_outcome", ev.VerifierOutcome(task_id="t1", verifier="v", passed=False, detail="d")),
        ("checkpoint_taken", ev.CheckpointTaken(task_id="t1", checkpoint_id="cp", ref="r")),
        ("terminal_outcome", ev.TerminalOutcome(task_id="t1", outcome="failed", detail="d")),
        ("role_transitioned", ev.RoleTransitioned(from_role="director", to_role="reviewer")),
    ]
    for event_type, struct in sequence:
        _emit(bus, event_type, struct)
    # incremental state (built on emit) must equal a from-scratch rebuild
    assert check_projection_rebuild_parity(conn, reg) is True
    assert conn.execute("SELECT role FROM proj_role_state WHERE id=1").fetchone()[0] == "reviewer"


def test_all_24_claim_names_registered_and_boot_passes():
    names = boot.registered_check_names()
    assert len(names) == len(boot.REQUIRED_GATES)
    for gate in ("workflow_guard", "secret_guard", "scope_guard", "sandbox"):
        assert gate in names
        assert boot.REQUIRED_GATES[gate] == "C1"
    assert boot.check_required_gates_registered() is True


def test_boot_fails_closed_if_a_name_missing(monkeypatch):
    monkeypatch.setitem(boot.REQUIRED_GATES, "check_made_up", "C7")
    with pytest.raises(boot.BootError):
        boot.check_required_gates_registered()
