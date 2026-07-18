"""Operator console scaffold: it launches, connects to the runtime, and reflects loop state
read-only from the projections, with an EventBus.emit_sync-only write posture (no direct
event-store or projection writes)."""

import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console import LoopState, read_loop_state
from devharness.console.app import ConsoleApp
from devharness.events.bus import EventBus


def _app():
    """A console connected to a fresh in-memory event store (migrated)."""
    return ConsoleApp(db_path=":memory:").connect()


def test_connects_and_arms_emit_only_writer():
    app = _app()
    # connected to the runtime: the migrated event store is reachable
    assert app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    # the only sanctioned write path is an EventBus (emit_sync), not a raw cursor
    assert isinstance(app.writer, EventBus)


def test_unconnected_app_refuses_access():
    app = ConsoleApp(db_path=":memory:")
    with pytest.raises(RuntimeError):
        _ = app.conn
    with pytest.raises(RuntimeError):
        _ = app.writer


def test_empty_loop_state():
    state = _app().loop_state()
    assert isinstance(state, LoopState)
    assert state.active_role is None
    assert state.spec_signed is False
    assert state.tasks_by_state == {}
    assert state.event_count == 0


def test_reflects_loop_state_from_projections():
    app = _app()
    bus = app.writer  # writes go through EventBus.emit_sync only

    bus.emit_sync("role_transitioned", {"to_role": "director"}, "c1")
    bus.emit_sync(
        "spec_signed",
        {"spec_id": "spec-7", "signer": "operator", "signed_at_millis": 100},
        "c1",
    )
    bus.emit_sync(
        "task_started",
        {"task_id": "t-1", "role": "developer", "worktree_path": "/wt", "started_at_millis": 200},
        "c1",
    )

    state = app.loop_state()
    assert state.active_role == "director"
    assert state.spec_signed is True
    assert state.signed_spec_id == "spec-7"
    assert state.signed_by == "operator"
    assert state.tasks_by_state == {"running": 1}
    assert state.event_count == 3


def test_render_is_a_readonly_string():
    app = _app()
    app.writer.emit_sync("role_transitioned", {"to_role": "research"}, "c1")
    before = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    text = app.render()
    assert "devharness operator console" in text
    assert "research" in text

    # rendering is read-only: it never appends an event or mutates the store
    after = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert after == before


def test_read_loop_state_does_not_write():
    conn = sqlite3.connect(":memory:")
    from devharness.migrate import migrate

    migrate(conn)
    before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    read_loop_state(conn)
    after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert after == before


# --- store-path hygiene (rev 0.3.63): resolve absolute, fail closed on a missing parent,
# --- announce a brand-new store (the wrong-cwd relative-DEVHARNESS_DB incident: sqlite gave a
# --- bare "unable to open database file" naming no path, and a writable wrong path would have
# --- silently created a fresh empty store the migrations make look legitimate).


def test_connect_missing_parent_dir_fails_closed_naming_the_resolved_path(tmp_path):
    bad = tmp_path / "no_such_dir" / "store.db"
    with pytest.raises(FileNotFoundError) as exc:
        ConsoleApp(db_path=str(bad)).connect()
    # the error names the RESOLVED absolute path (the whole point — sqlite's own error names none)
    assert str(bad.parent) in str(exc.value)
    assert not bad.exists()  # fail-closed: nothing was created


def test_connect_relative_path_resolves_absolute_and_flags_creation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = ConsoleApp(db_path="store.db").connect()
    assert Path(app.db_path).is_absolute()
    assert app.db_path == str(tmp_path / "store.db")
    assert app.store_created is True  # a brand-new store is announced, never silent
    # the created store is real and migrated
    assert app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_connect_existing_store_is_not_flagged_created(tmp_path):
    db = tmp_path / "store.db"
    ConsoleApp(db_path=str(db)).connect()  # first connect creates it
    app = ConsoleApp(db_path=str(db)).connect()
    assert app.store_created is False


def test_connect_memory_store_is_untouched_by_path_hygiene():
    app = ConsoleApp(db_path=":memory:").connect()
    assert app.db_path == ":memory:"
    assert app.store_created is False


def test_console_source_has_no_direct_write_sql():
    """Structural guard for the emit_sync-only posture: the console package issues no
    INSERT/UPDATE/DELETE — every read is SELECT, and writes are EventBus.emit_sync's job."""
    pkg = Path(__file__).resolve().parents[2] / "runtime" / "devharness" / "console"
    # match real SQL write STATEMENTS, not the bare word — docstrings/prose legitimately say "delete"
    # (e.g. the §S6 "delete path"); a direct write is INSERT INTO / DELETE FROM / UPDATE <table> SET.
    forbidden = re.compile(r"\bINSERT\s+INTO\b|\bDELETE\s+FROM\b|\bUPDATE\s+[\w.]+\s+SET\b", re.IGNORECASE)
    offenders = []
    for src in pkg.glob("*.py"):
        for lineno, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if forbidden.search(code):
                offenders.append(f"{src.name}:{lineno}: {line.strip()}")
    assert not offenders, "direct write SQL in the read-only console:\n" + "\n".join(offenders)
