"""B5.3: gate-change validator — core-gate weakening rejected; tightening + non-core allowed."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.gate_change_validator import CORE_GATES, validate_gate_change_candidate, would_weaken_core_gate


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _candidate(bus, target_gate, change_kind, source="llm"):
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s",
                  "target_gate": target_gate, "change_kind": change_kind, "change_details": {},
                  "evidence_event_ids": [], "source": source, "created_at_millis": 1}, correlation_id="c")


def test_would_weaken_logic():
    for g in CORE_GATES:
        assert would_weaken_core_gate(g, "loosen") and would_weaken_core_gate(g, "remove_signature")
        assert not would_weaken_core_gate(g, "tighten") and not would_weaken_core_gate(g, "add_signature")
    assert not would_weaken_core_gate("cost_mode_gate", "loosen")  # non-core


def test_core_weakening_rejected_and_emits_event():
    conn, bus = _setup()
    _candidate(bus, "secret_guard", "loosen")
    row_id = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue").fetchone()[0]
    result = validate_gate_change_candidate(row_id, conn, bus, now_millis=lambda: 5)
    assert result.valid is False and result.rejection_reason == "core_gate_weakening"
    ev = conn.execute("SELECT json_extract(payload,'$.rejection_reason'), json_extract(payload,'$.auto_rejected') FROM events WHERE event_type='gate_change_rejected'").fetchone()
    assert ev == ("core_gate_weakening", 1)


def test_core_tightening_allowed():
    conn, bus = _setup()
    _candidate(bus, "scope_guard", "tighten")
    row_id = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue").fetchone()[0]
    assert validate_gate_change_candidate(row_id, conn, bus).valid is True
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE gate_change_row_id=?", (row_id,)).fetchone()[0] == "pending"


def test_non_core_change_allowed():
    conn, bus = _setup()
    _candidate(bus, "cost_mode_gate", "loosen", source="t0")
    row_id = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue").fetchone()[0]
    assert validate_gate_change_candidate(row_id, conn, bus).valid is True
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE gate_change_row_id=?", (row_id,)).fetchone()[0] == "pending"


def test_casing_and_whitespace_cannot_evade_core_gate_weakening():
    # the queue's target_gate has no CHECK constraint; a crafted spelling must still be caught (audit)
    from devharness.retro.enacted_gate_changes import is_enactable
    for tg in ("WORKFLOW_GUARD", " workflow_guard", "Workflow_Guard ", "secret_guard"):
        assert would_weaken_core_gate(tg, "loosen") is True
        assert would_weaken_core_gate(tg, " LOOSEN ") is True
    assert would_weaken_core_gate("workflow_guard", "tighten") is False   # tightening still allowed


def test_is_enactable_rejects_whitespace_and_non_string_signatures():
    from devharness.retro.enacted_gate_changes import is_enactable
    assert is_enactable("antibody_screen", "add_signature", {"signature": "real_marker"}) is True
    assert is_enactable("antibody_screen", "add_signature", {"signature": "   "}) is False   # whitespace DoS
    assert is_enactable("antibody_screen", "add_signature", {"signature": ""}) is False
    assert is_enactable("antibody_screen", "add_signature", {"signature": 123}) is False      # non-string TypeError
    assert is_enactable("antibody_screen", "add_signature", {}) is False
