"""B5.5: Inv 17 graduation — cross-project memory is verified before trusted."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.memory.store import create_memory_entry, list_verified_memory, verify_memory_entry
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def test_inv_17_boot_check_passes():
    assert boot.check_inv_17_verified_before_trusted() is True


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_imported_entry_untrusted_until_verified():
    conn, bus = _setup()
    bus.emit_sync("memory_entry_created", {"entry_id": "imp", "entry_type": "antibody", "entry_payload_json": "{}", "source_project": "sibling-agent", "created_at_millis": 1}, correlation_id="c")
    assert [e.entry_id for e in list_verified_memory(conn)] == []  # not trusted on arrival
    verify_memory_entry("imp", {"verifier": "feature_spec_claim", "evidence": "re-checked locally"}, "operator", conn, bus, now_millis=lambda: 9)
    assert [e.entry_id for e in list_verified_memory(conn)] == ["imp"]  # trusted after local verification
    assert "feature_spec_claim" in conn.execute("SELECT verifier_evidence_json FROM proj_memory WHERE entry_id='imp'").fetchone()[0]


def test_local_entry_trusted_from_start():
    conn, bus = _setup()
    eid = create_memory_entry("antibody", {"pattern_text": "x"}, conn, bus, now_millis=lambda: 1)
    assert [e.entry_id for e in list_verified_memory(conn)] == [eid]
