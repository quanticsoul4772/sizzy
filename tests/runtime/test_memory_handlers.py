"""B5.5: memory handlers — create (local/imported) + verify; rebuild parity."""

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


def test_created_local_vs_imported():
    conn, _registry, bus = _setup()
    bus.emit_sync("memory_entry_created", {"entry_id": "loc", "entry_type": "antibody", "entry_payload_json": "{}", "source_project": "devharness", "created_at_millis": 1}, correlation_id="c")
    bus.emit_sync("memory_entry_created", {"entry_id": "imp", "entry_type": "antibody", "entry_payload_json": "{}", "source_project": "other", "created_at_millis": 2}, correlation_id="c")
    assert conn.execute("SELECT verified_locally FROM proj_memory WHERE entry_id='loc'").fetchone()[0] == 1
    assert conn.execute("SELECT verified_locally FROM proj_memory WHERE entry_id='imp'").fetchone()[0] == 0


def test_verified_updates_row():
    conn, _registry, bus = _setup()
    bus.emit_sync("memory_entry_created", {"entry_id": "imp", "entry_type": "antibody", "entry_payload_json": "{}", "source_project": "other", "created_at_millis": 1}, correlation_id="c")
    bus.emit_sync("memory_entry_verified", {"entry_id": "imp", "verifier_evidence_json": '{"verifier":"v"}', "verified_by": "op", "verified_at_millis": 9}, correlation_id="c")
    row = conn.execute("SELECT verified_locally, verified_at_millis, verifier_evidence_json FROM proj_memory WHERE entry_id='imp'").fetchone()
    assert row == (1, 9, '{"verifier":"v"}')


def test_rebuild_parity_mixed():
    conn, registry, bus = _setup()
    bus.emit_sync("memory_entry_created", {"entry_id": "loc", "entry_type": "antibody", "entry_payload_json": "{}", "source_project": "devharness", "created_at_millis": 1}, correlation_id="c")
    bus.emit_sync("memory_entry_created", {"entry_id": "imp", "entry_type": "antibody", "entry_payload_json": "{}", "source_project": "other", "created_at_millis": 2}, correlation_id="c")
    bus.emit_sync("memory_entry_verified", {"entry_id": "imp", "verifier_evidence_json": "{}", "verified_by": "op", "verified_at_millis": 9}, correlation_id="c")
    assert check_projection_rebuild_parity(conn, registry) is True
