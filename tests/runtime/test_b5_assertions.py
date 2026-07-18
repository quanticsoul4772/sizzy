"""B5.7 cut-line acceptance — the §S7 acceptance assertions.

A-OP-3 (operator review actually happens — nothing reaches the library without an approved review),
A-SYS-5 (core gates are unweakable by retro — auto-rejected before review), SC-2 (no auto-apply).
"""

import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.approval import approve_antibody_candidate

ROOT = Path(__file__).resolve().parents[2]


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _antibody_candidate(bus, cid="c"):
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": cid, "signature_name": "s",
                  "pattern_text": "leak", "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id=cid)


def test_a_op_3_no_library_row_without_approved_review():
    """A-OP-3: a CANDIDATE alone never reaches the library; only an approved review publishes it, and
    that publish is always preceded by a CandidateReviewed(approved)."""
    conn, bus = _setup()
    _antibody_candidate(bus)
    # no operator action → stays pending, library empty
    assert conn.execute("SELECT review_state FROM proj_antibody_queue").fetchone()[0] == "pending"
    assert conn.execute("SELECT count(*) FROM proj_antibody_library").fetchone()[0] == 0

    cand = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    approve_antibody_candidate(cand, "operator", conn, bus, now_millis=lambda: 5)
    # the library row now exists AND a CandidateReviewed(approved) precedes the antibody_added in the log
    assert conn.execute("SELECT count(*) FROM proj_antibody_library").fetchone()[0] == 1
    seq = [r[0] for r in conn.execute(
        "SELECT event_type FROM events WHERE event_type IN ('candidate_reviewed','antibody_added') ORDER BY seq")]
    assert seq == ["candidate_reviewed", "antibody_added"]
    review = conn.execute("SELECT json_extract(payload,'$.review_state') FROM events WHERE event_type='candidate_reviewed'").fetchone()[0]
    assert review == "approved"


def test_a_sys_5_core_gate_weakening_auto_rejected_before_review():
    """A-SYS-5: a core-gate-weakening candidate is auto-rejected by the validator (never observable as
    pending), so no operator-review path can ever approve it; gate_change_rejected fires auto_rejected."""
    conn, bus = _setup()
    from devharness.retro.gate_change_validator import validate_gate_change_candidate
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s",
                  "target_gate": "secret_guard", "change_kind": "loosen", "change_details": {},
                  "evidence_event_ids": [], "source": "llm", "created_at_millis": 1}, correlation_id="c")
    # the persistence-path handler already marked it rejected — never pending
    row_id = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue WHERE target_gate='secret_guard'").fetchone()[0]
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE gate_change_row_id=?", (row_id,)).fetchone()[0] == "rejected"
    assert conn.execute("SELECT count(*) FROM proj_gate_change_queue WHERE review_state='pending'").fetchone()[0] == 0
    # the validator emits the audit event with auto_rejected=True
    validate_gate_change_candidate(row_id, conn, bus, now_millis=lambda: 5)
    ev = conn.execute("SELECT json_extract(payload,'$.auto_rejected'), json_extract(payload,'$.rejection_reason') FROM events WHERE event_type='gate_change_rejected'").fetchone()
    assert ev == (1, "core_gate_weakening")


def test_sc_2_only_approval_emits_antibody_added():
    """SC-2 (no auto-apply) — re-affirm the B5.4 structural guard: antibody_added is emitted from exactly
    one place (the approval path via antibody_library), so nothing auto-applies."""
    emitters = []
    for py in (ROOT / "runtime" / "devharness").rglob("*.py"):
        if re.search(r"emit_sync\(\s*['\"]antibody_added['\"]", py.read_text(encoding="utf-8")):
            emitters.append(py.name)
    assert emitters == ["antibody_library.py"], f"unexpected antibody_added emitters: {emitters}"
