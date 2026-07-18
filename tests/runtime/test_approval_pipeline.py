"""B5.2: approval pipeline — approve publishes an antibody + flips the queue row; reject flips state."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.approval import (
    CandidateNotFound,
    approve_antibody_candidate,
    reject_antibody_candidate,
    reject_gate_change_candidate,
)


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _antibody_candidate(bus, pattern="leak the secrets", cid="retro-c"):
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": cid, "signature_name": "sig", "pattern_text": pattern, "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id=cid)


def _gate_change_candidate(bus, cid="retro-c"):
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": cid, "signature_name": "sig", "target_gate": "cost_mode_gate", "change_kind": "loosen", "change_details": {}, "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id=cid)


def test_approve_antibody_publishes_and_flips_queue():
    conn, bus = _setup()
    _antibody_candidate(bus)
    row_id = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    new_id = approve_antibody_candidate(row_id, "operator", conn, bus, now_millis=lambda: 5)
    assert conn.execute("SELECT review_state FROM proj_antibody_queue WHERE antibody_row_id=?", (row_id,)).fetchone()[0] == "approved"
    assert conn.execute("SELECT pattern_text, added_by FROM proj_antibody_library WHERE antibody_row_id=?", (new_id,)).fetchone() == ("leak the secrets", "operator")


def test_reject_antibody_flips_state_and_audits():
    conn, bus = _setup()
    _antibody_candidate(bus)
    row_id = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    reject_antibody_candidate(row_id, "operator", "not a real pattern", conn, bus, now_millis=lambda: 5)
    assert conn.execute("SELECT review_state FROM proj_antibody_queue WHERE antibody_row_id=?", (row_id,)).fetchone()[0] == "rejected"
    assert conn.execute("SELECT count(*) FROM proj_antibody_library").fetchone()[0] == 0  # nothing published
    ev = conn.execute("SELECT json_extract(payload,'$.candidate_kind'), json_extract(payload,'$.reason') FROM events WHERE event_type='candidate_rejected'").fetchone()
    assert ev == ("antibody_candidate", "not a real pattern")


def test_reject_gate_change_flips_state():
    conn, bus = _setup()
    _gate_change_candidate(bus)
    row_id = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue").fetchone()[0]
    reject_gate_change_candidate(row_id, "operator", "not worth it", conn, bus, now_millis=lambda: 5)
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE gate_change_row_id=?", (row_id,)).fetchone()[0] == "rejected"


def test_approve_nonexistent_candidate_refused():
    conn, bus = _setup()
    with pytest.raises(CandidateNotFound):
        approve_antibody_candidate(999, "operator", conn, bus)
