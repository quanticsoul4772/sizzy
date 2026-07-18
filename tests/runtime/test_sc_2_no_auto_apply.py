"""B5.4: SC-2 — no retro-produced change reaches the harness without an explicit operator approval.

Structurally enforced: the only path from an antibody_candidate to a proj_antibody_library row is
approve_antibody_candidate (which emits antibody_added). No other code emits antibody_added.
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

RUNTIME = Path(__file__).resolve().parents[2] / "runtime" / "devharness"


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_candidate_alone_does_not_publish():
    conn, bus = _setup()
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "pattern_text": "p", "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    # without an explicit approve, the candidate stays pending and nothing reaches the library
    assert conn.execute("SELECT review_state FROM proj_antibody_queue").fetchone()[0] == "pending"
    assert conn.execute("SELECT count(*) FROM proj_antibody_library").fetchone()[0] == 0


def test_only_approval_emits_antibody_added():
    # greppable structural assertion: antibody_added is emitted only from antibody_library.add_antibody,
    # which is only reached via approve_antibody_candidate (the operator path).
    emitters = []
    for py in RUNTIME.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if re.search(r"emit_sync\(\s*['\"]antibody_added['\"]", text):
            emitters.append(py.name)
    assert emitters == ["antibody_library.py"], f"unexpected antibody_added emitters: {emitters}"


def test_auto_rejection_is_not_auto_apply():
    # a B5.3 validator auto-reject is a REJECTION (review_state=rejected), not an enactment
    conn, bus = _setup()
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s", "target_gate": "secret_guard", "change_kind": "loosen", "change_details": {}, "evidence_event_ids": [], "source": "llm", "created_at_millis": 1}, correlation_id="c")
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE target_gate='secret_guard'").fetchone()[0] == "rejected"
    types = {r[0] for r in conn.execute("SELECT DISTINCT event_type FROM events")}
    assert not any("applied" in t or "enacted" in t for t in types)
