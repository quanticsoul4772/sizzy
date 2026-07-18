"""B5.2: antibody_added / antibody_revoked / candidate_rejected handlers; rebuild parity."""

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


def test_added_is_pure_projection_no_queue_flip():
    # B5.4: antibody_added inserts the library row ONLY — it no longer flips the queue (candidate_reviewed
    # drives the review transition now). Regression guard against the superseded B5.2 side-effect.
    conn, _registry, bus = _setup()
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "pattern_text": "p", "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    cand_id = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    bus.emit_sync("antibody_added", {"antibody_row_id": 1, "pattern_text": "p", "source_candidate_id": str(cand_id), "added_by": "op", "added_at_millis": 2}, correlation_id="c")
    assert conn.execute("SELECT pattern_text FROM proj_antibody_library WHERE antibody_row_id=1").fetchone()[0] == "p"
    # the queue row is STILL pending — antibody_added did not flip it
    assert conn.execute("SELECT review_state FROM proj_antibody_queue WHERE antibody_row_id=?", (cand_id,)).fetchone()[0] == "pending"


def test_revoked_updates_library():
    conn, _registry, bus = _setup()
    bus.emit_sync("antibody_added", {"antibody_row_id": 1, "pattern_text": "p", "source_candidate_id": "0", "added_by": "op", "added_at_millis": 1}, correlation_id="c")
    bus.emit_sync("antibody_revoked", {"antibody_row_id": 1, "reason": "dupe", "revoked_by": "op", "revoked_at_millis": 9}, correlation_id="c")
    assert conn.execute("SELECT revoked_at_millis, revoke_reason FROM proj_antibody_library WHERE antibody_row_id=1").fetchone() == (9, "dupe")


def test_candidate_rejected_routes_by_kind():
    conn, _registry, bus = _setup()
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "target_gate": "cost_mode_gate", "change_kind": "loosen", "change_details": {}, "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    gc_id = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue").fetchone()[0]
    bus.emit_sync("candidate_rejected", {"candidate_row_id": gc_id, "candidate_kind": "gate_change_candidate", "rejected_by": "op", "reason": "no", "rejected_at_millis": 2}, correlation_id="c")
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE gate_change_row_id=?", (gc_id,)).fetchone()[0] == "rejected"


def test_rebuild_parity_mixed():
    conn, registry, bus = _setup()
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "pattern_text": "p", "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    cand_id = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    bus.emit_sync("antibody_added", {"antibody_row_id": 1, "pattern_text": "p", "source_candidate_id": str(cand_id), "added_by": "op", "added_at_millis": 2}, correlation_id="c")
    bus.emit_sync("antibody_revoked", {"antibody_row_id": 1, "reason": "dupe", "revoked_by": "op", "revoked_at_millis": 3}, correlation_id="c")
    assert check_projection_rebuild_parity(conn, registry) is True
