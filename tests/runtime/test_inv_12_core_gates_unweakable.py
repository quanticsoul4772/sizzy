"""B5.3: Inv 12 graduation — core gates are unweakable by retro."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro import llm_residue
from devharness.retro.approval import reject_gate_change_candidate
from devharness.retro.gate_change_validator import CORE_GATES


def test_inv_12_boot_check_passes():
    assert boot.check_inv_12_core_gates_unweakable() is True


def test_core_gates_exact_seven():
    assert CORE_GATES == {"workflow_guard", "secret_guard", "scope_guard", "sandbox",
                          "write_lock_gate", "spec_signed_gate", "verifier_attached_gate"}


def test_llm_filter_and_validator_share_set_object():
    assert llm_residue.CORE_GATES is CORE_GATES  # single source of truth, same object


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_weakening_candidate_auto_rejected_within_one_tick():
    conn, bus = _setup()
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s",
                  "target_gate": "sandbox", "change_kind": "remove_signature", "change_details": {},
                  "evidence_event_ids": [], "source": "llm", "created_at_millis": 1}, correlation_id="c")
    # rejected by the persistence-path handler in the same emit — never observable as 'pending'
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE target_gate='sandbox'").fetchone()[0] == "rejected"


def test_non_core_candidate_stays_pending():
    conn, bus = _setup()
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s",
                  "target_gate": "cost_mode_gate", "change_kind": "loosen", "change_details": {},
                  "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE target_gate='cost_mode_gate'").fetchone()[0] == "pending"
