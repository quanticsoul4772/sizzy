"""B5.4: regression — antibody_added is a pure projection; the queue transition is driven only by
candidate_reviewed (the B5.2 antibody_added queue-flip side-effect is gone)."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_antibody_added_does_not_flip_queue():
    conn, bus = _setup()
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "pattern_text": "p", "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    cand = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    # antibody_added alone (no candidate_reviewed) must NOT change review_state
    bus.emit_sync("antibody_added", {"antibody_row_id": 1, "pattern_text": "p", "source_candidate_id": str(cand), "added_by": "op", "added_at_millis": 2}, correlation_id="c")
    assert conn.execute("SELECT review_state FROM proj_antibody_queue WHERE antibody_row_id=?", (cand,)).fetchone()[0] == "pending"


def test_only_candidate_reviewed_flips_queue():
    conn, bus = _setup()
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "pattern_text": "p", "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    cand = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    bus.emit_sync("candidate_reviewed", {"candidate_row_id": cand, "candidate_kind": "antibody_candidate", "review_state": "approved", "reviewed_by": "op", "review_reason": "", "reviewed_at_millis": 3}, correlation_id="c")
    assert conn.execute("SELECT review_state, reviewed_by FROM proj_antibody_queue WHERE antibody_row_id=?", (cand,)).fetchone() == ("approved", "op")
