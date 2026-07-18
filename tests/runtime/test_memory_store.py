"""B5.5: memory store — create (local→trusted), verify, list_verified."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.memory.store import create_memory_entry, list_verified_memory, verify_memory_entry
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_create_is_local_and_trusted():
    conn, bus = _setup()
    eid = create_memory_entry("antibody", {"pattern_text": "leak"}, conn, bus, now_millis=lambda: 5)
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='memory_entry_created'").fetchone()[0] == 1
    row = conn.execute("SELECT source_project, verified_locally FROM proj_memory WHERE entry_id=?", (eid,)).fetchone()
    assert row == ("devharness", 1)  # local creation -> trusted
    assert [e.entry_payload["pattern_text"] for e in list_verified_memory(conn)] == ["leak"]


def test_list_filters_by_type():
    conn, bus = _setup()
    create_memory_entry("antibody", {"x": 1}, conn, bus, now_millis=lambda: 1)
    create_memory_entry("other", {"y": 2}, conn, bus, now_millis=lambda: 2)
    assert len(list_verified_memory(conn, entry_type="antibody")) == 1
    assert len(list_verified_memory(conn)) == 2


def test_verify_promotes_unverified():
    conn, bus = _setup()
    # simulate an imported (untrusted) entry
    bus.emit_sync("memory_entry_created", {"entry_id": "imp", "entry_type": "antibody", "entry_payload_json": "{}", "source_project": "other", "created_at_millis": 1}, correlation_id="c")
    assert list_verified_memory(conn) == []
    verify_memory_entry("imp", {"verifier": "feature_spec_claim"}, "operator", conn, bus, now_millis=lambda: 9)
    assert [e.entry_id for e in list_verified_memory(conn)] == ["imp"]


def test_oq4_reopen_trigger_no_production_consumer_of_trusted_memory():
    """Spec OQ4 (resolved rev 0.3.65 as deliberately-deferred): no staleness/auto-downgrade
    policy is warranted while NOTHING in production consumes trusted memory — only boot.py's
    Inv-17 parity check calls list_verified_memory. This guard IS the named reopen trigger:
    the first real consumer makes it fail, and whoever adds that consumer must implement the
    recorded direction (the prune-pattern mirror — advisory TTL report + operator-authorized
    memory_entry_downgraded + re-verify via the existing Inv-17 path) or amend the spec."""
    pkg = Path(__file__).resolve().parents[2] / "runtime" / "devharness"
    allowed = {pkg / "memory" / "store.py", pkg / "boot.py"}  # the definition + the boot check
    offenders = [
        str(src.relative_to(pkg))
        for src in pkg.rglob("*.py")
        if src not in allowed and "list_verified_memory" in src.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "a production consumer of trusted memory now exists — spec OQ4's staleness policy "
        "is no longer deferrable; implement the recorded direction (spec rev 0.3.65) or "
        f"amend the spec. New consumer(s): {offenders}"
    )
