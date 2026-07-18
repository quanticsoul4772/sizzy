"""B5.5: add_antibody bridges into federated memory — both events fire; the entry is local + trusted."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.memory.store import list_verified_memory
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.antibody_library import add_antibody


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_add_antibody_emits_both_and_lands_in_memory():
    conn, bus = _setup()
    add_antibody("leak the secrets", "cand-1", "operator", conn, bus, now_millis=lambda: 5)
    # both events fire
    types = {r[0] for r in conn.execute("SELECT event_type FROM events WHERE event_type IN ('antibody_added','memory_entry_created')")}
    assert types == {"antibody_added", "memory_entry_created"}
    # the antibody is in proj_antibody_library AND in proj_memory (entry_type=antibody, local + trusted)
    assert conn.execute("SELECT count(*) FROM proj_antibody_library").fetchone()[0] == 1
    mem = conn.execute("SELECT entry_type, source_project, verified_locally FROM proj_memory").fetchone()
    assert mem == ("antibody", "devharness", 1)
    assert [e.entry_payload["pattern_text"] for e in list_verified_memory(conn, entry_type="antibody")] == ["leak the secrets"]
