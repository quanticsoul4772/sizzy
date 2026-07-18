"""B5.5: export_memory writes a portable artifact of memory_entry_created payloads (no verification state)."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.memory.export_import import export_memory
from devharness.memory.store import create_memory_entry, verify_memory_entry
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_export_structure_and_entries(tmp_path):
    conn, bus = _setup()
    create_memory_entry("antibody", {"pattern_text": "leak"}, conn, bus, now_millis=lambda: 5)
    create_memory_entry("antibody", {"pattern_text": "rm -rf"}, conn, bus, now_millis=lambda: 6)
    path = tmp_path / "mem.json"
    n = export_memory(str(path), conn, now_millis=lambda: 100)
    assert n == 2
    art = json.loads(path.read_text())
    assert art["project_name"] == "devharness" and art["export_at_millis"] == 100
    assert {json.loads(e["entry_payload_json"])["pattern_text"] for e in art["entries"]} == {"leak", "rm -rf"}
    # original timestamps preserved
    assert {e["created_at_millis"] for e in art["entries"]} == {5, 6}


def test_export_omits_verification_state(tmp_path):
    conn, bus = _setup()
    eid = create_memory_entry("antibody", {"pattern_text": "x"}, conn, bus, now_millis=lambda: 5)
    verify_memory_entry(eid, {"verifier": "v"}, "op", conn, bus, now_millis=lambda: 9)
    art = json.loads((lambda p: (export_memory(str(p), conn), p)[1])(tmp_path / "m.json").read_text())
    # the exported entry carries no verified_locally / verifier_evidence fields (each project verifies independently)
    e = art["entries"][0]
    assert "verified_locally" not in e and "verifier_evidence_json" not in e
