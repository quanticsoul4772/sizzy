"""rev 0.4.13: foreign sqlite files are invisible to the store surfaces.

Live: the deployed panel's notice named ``parallax.db`` — the parallax MCP server's OWN database,
co-located in ``var/`` by the VPS bootstrap — as the freshest store (no events table → the
activity ranking fell back to file mtime, always fresh for a constantly-written MCP db). Every
open path runs ``migrate()`` on connect, so adopting a foreign file writes devharness schema INTO
it. ``is_event_store`` is the tri-state read-only probe every surface now consults.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.migrate import is_event_store


def _real_store(path) -> None:
    from devharness.panel.writer import PanelWriter

    w = PanelWriter(str(path))
    w.close()


def _foreign_db(path) -> None:
    """The parallax.db shape: a healthy sqlite database that is not a devharness store."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, text TEXT)")
    conn.execute("INSERT INTO memories (text) VALUES ('not yours')")
    conn.commit()
    conn.close()


def test_is_event_store_tri_state(tmp_path, monkeypatch):
    real = tmp_path / "real.db"
    _real_store(real)
    assert is_event_store(real) is True

    assert is_event_store(tmp_path / "missing.db") is False

    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"this is not sqlite at all, padding padding padding")
    assert is_event_store(garbage) is False

    foreign = tmp_path / "parallax.db"
    _foreign_db(foreign)
    assert is_event_store(foreign) is False

    # unreadable-right-now (locked WAL — not deterministically reproducible in-process) → None,
    # never False: a transiently-locked REAL store must not be misclassified as foreign
    import devharness.migrate as m

    def always_locked(*a, **kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(m.sqlite3, "connect", always_locked)
    assert is_event_store(real) is None


def test_probe_never_modifies_the_target(tmp_path):
    foreign = tmp_path / "parallax.db"
    _foreign_db(foreign)
    before = foreign.read_bytes()
    assert is_event_store(foreign) is False
    assert foreign.read_bytes() == before  # byte-identical — probed, never migrated/created


def test_console_open_refuses_a_foreign_store(tmp_path):
    from devharness.console.app import ConsoleApp

    foreign = tmp_path / "parallax.db"
    _foreign_db(foreign)
    with pytest.raises(FileNotFoundError, match="not a devharness event store"):
        ConsoleApp(db_path=str(foreign)).connect()
    # untouched: no devharness schema was written into the foreign database
    conn = sqlite3.connect(f"file:{foreign.resolve().as_posix()}?mode=ro", uri=True)
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name IN ('events','schema_migrations')").fetchone() is None
    conn.close()
