"""B5.5: import_memory — entries land untrusted; idempotent; monotonic (downgrade guard)."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.memory.export_import import import_memory
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _artifact(tmp_path, entries, name="a.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"project_name": "other", "export_at_millis": 1, "entries": entries}))
    return str(path)


def _entry(eid, at, project="other"):
    return {"entry_id": eid, "entry_type": "antibody", "entry_payload_json": '{"pattern_text": "x"}',
            "source_project": project, "created_at_millis": at, "correlation_id": "c"}


def test_import_lands_untrusted(tmp_path):
    conn, bus = _setup()
    n = import_memory(_artifact(tmp_path, [_entry("e1", 5), _entry("e2", 6)]), conn, bus)
    assert n == 2
    assert {r[0] for r in conn.execute("SELECT verified_locally FROM proj_memory")} == {0}  # all untrusted


def test_import_idempotent(tmp_path):
    conn, bus = _setup()
    art = _artifact(tmp_path, [_entry("e1", 5)])
    assert import_memory(art, conn, bus) == 1
    assert import_memory(art, conn, bus) == 0  # duplicate entry_id skipped
    assert conn.execute("SELECT count(*) FROM proj_memory").fetchone()[0] == 1


def test_import_monotonic_rejects_downgrade(tmp_path):
    conn, bus = _setup()
    import_memory(_artifact(tmp_path, [_entry("e2", 100)], "first.json"), conn, bus)
    # a NEW entry from the same source_project older than the latest known (100) is rejected
    assert import_memory(_artifact(tmp_path, [_entry("e1", 50)], "old.json"), conn, bus) == 0
    # but a newer one is accepted
    assert import_memory(_artifact(tmp_path, [_entry("e3", 150)], "new.json"), conn, bus) == 1
