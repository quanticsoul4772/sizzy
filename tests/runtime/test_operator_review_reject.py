"""B5.4: reject — candidate_reviewed(rejected) + candidate_rejected; nothing publishes."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.approval import reject_antibody_candidate, reject_gate_change_candidate


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_reject_antibody_emits_both_and_publishes_nothing():
    conn, bus = _setup()
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "pattern_text": "p", "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    cand = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    reject_antibody_candidate(cand, "operator", "not a real pattern", conn, bus, now_millis=lambda: 5)

    types = {r[0] for r in conn.execute("SELECT event_type FROM events WHERE event_type IN ('candidate_reviewed','candidate_rejected')")}
    assert types == {"candidate_reviewed", "candidate_rejected"}  # both fire (backward compat)
    row = conn.execute("SELECT review_state, reviewed_by FROM proj_antibody_queue WHERE antibody_row_id=?", (cand,)).fetchone()
    assert row == ("rejected", "operator")
    assert conn.execute("SELECT count(*) FROM proj_antibody_library").fetchone()[0] == 0  # nothing published


def test_reject_gate_change():
    conn, bus = _setup()
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "target_gate": "cost_mode_gate", "change_kind": "loosen", "change_details": {}, "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    gc = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue").fetchone()[0]
    reject_gate_change_candidate(gc, "operator", "not worth it", conn, bus, now_millis=lambda: 5)
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE gate_change_row_id=?", (gc,)).fetchone()[0] == "rejected"


def test_reject_requires_reason():
    conn, bus = _setup()
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "pattern_text": "p", "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    cand = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    with pytest.raises(ValueError):
        reject_antibody_candidate(cand, "operator", "", conn, bus)
