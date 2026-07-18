"""B5.5: memory export/import CLI round-trip across projects (verified_locally federated)."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.memory.export_import import export_memory, import_memory
from devharness.memory.store import create_memory_entry
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _store():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_export_from_one_project_import_into_another(tmp_path, monkeypatch):
    # project A creates a local (trusted-in-A) entry and exports it
    monkeypatch.setenv("DEVHARNESS_PROJECT_NAME", "agent-harness")
    conn_a, bus_a = _store()
    create_memory_entry("antibody", {"pattern_text": "shared learning"}, conn_a, bus_a, now_millis=lambda: 5)
    art = tmp_path / "a.json"
    assert export_memory(str(art), conn_a) == 1

    # project B imports it -> lands UNTRUSTED (source_project=agent-harness != devharness)
    monkeypatch.setenv("DEVHARNESS_PROJECT_NAME", "devharness")
    conn_b, bus_b = _store()
    assert import_memory(str(art), conn_b, bus_b) == 1
    row = conn_b.execute("SELECT source_project, verified_locally FROM proj_memory").fetchone()
    assert row == ("agent-harness", 0)  # imported, untrusted until B verifies it locally


def test_memory_cli_main_export(tmp_path, monkeypatch):
    from devharness.cli import memory as cli
    db = tmp_path / "db.sqlite"
    monkeypatch.setenv("DEVHARNESS_DB", str(db))
    # seed one entry via a direct store on the same DB file
    conn = sqlite3.connect(str(db)); migrate(conn)
    registry = ProjectionRegistry(); register_handlers(registry)
    create_memory_entry("antibody", {"pattern_text": "x"}, conn, EventBus(conn, registry), now_millis=lambda: 1)
    conn.commit(); conn.close()
    out = tmp_path / "out.json"
    assert cli.main(["export", str(out)]) == 0
    assert out.exists()
