"""B5.4: approve — candidate_reviewed(approved) drives the queue transition; antibody publishes."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.approval import approve_antibody_candidate, approve_gate_change_candidate


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_approve_antibody_reviewed_then_added():
    conn, bus = _setup()
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "pattern_text": "leak secrets", "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    cand = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    new_id = approve_antibody_candidate(cand, "operator", conn, bus, now_millis=lambda: 5)

    # candidate_reviewed(approved) fires BEFORE antibody_added (the queue is approved when the library row lands)
    seq = [r[0] for r in conn.execute("SELECT event_type FROM events WHERE event_type IN ('candidate_reviewed','antibody_added') ORDER BY seq")]
    assert seq == ["candidate_reviewed", "antibody_added"]
    row = conn.execute("SELECT review_state, reviewed_by FROM proj_antibody_queue WHERE antibody_row_id=?", (cand,)).fetchone()
    assert row == ("approved", "operator")
    assert conn.execute("SELECT pattern_text FROM proj_antibody_library WHERE antibody_row_id=?", (new_id,)).fetchone()[0] == "leak secrets"


def test_approve_gate_change_no_enactment():
    conn, bus = _setup()
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "target_gate": "cost_mode_gate", "change_kind": "loosen", "change_details": {}, "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    gc = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue").fetchone()[0]
    approve_gate_change_candidate(gc, "operator", conn, bus, now_millis=lambda: 5)
    assert conn.execute("SELECT review_state, reviewed_by FROM proj_gate_change_queue WHERE gate_change_row_id=?", (gc,)).fetchone() == ("approved", "operator")
    # B5.4 does not enact gate changes: no apply event of any kind
    types = {r[0] for r in conn.execute("SELECT DISTINCT event_type FROM events")}
    assert not any("applied" in t for t in types)
