"""rev 0.3.80: the operator CLIs share the console's rev-0.3.63 store-path hygiene.

Every `devharness` CLI (sign/answer/retro/prune/ratify/memory/questions/work_items) opened its store
with a raw `sqlite3.connect(DEVHARNESS_DB)` — a relative/typo'd path against the wrong cwd either
failed bare or silently CREATED a phantom store that migrate() legitimized (an operator `sign` would
land in the wrong store — the CLI sibling of the wrong-target contamination). `open_store` centralizes
the console's fix: resolve to absolute, fail closed on a missing parent, announce a created store.
"""

import io
import contextlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cli._bus import open_store


@pytest.fixture
def _clean_env(monkeypatch):
    monkeypatch.delenv("DEVHARNESS_DB", raising=False)
    yield monkeypatch


def test_missing_parent_dir_fails_closed_naming_the_path(_clean_env):
    _clean_env.setenv("DEVHARNESS_DB", "/no/such/dir/store.db")
    with pytest.raises(SystemExit) as exc:
        open_store()
    assert "event-store directory does not exist" in str(exc.value)
    assert "store.db" in str(exc.value)  # the resolved path is named


def test_new_store_is_created_but_announced(_clean_env, tmp_path):
    _clean_env.setenv("DEVHARNESS_DB", str(tmp_path / "fresh.db"))
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        conn = open_store()
    try:
        assert "created NEW EMPTY event store" in err.getvalue()  # announced, never silent
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0  # migrated + empty
    finally:
        conn.close()


def test_existing_store_opens_silently(_clean_env, tmp_path):
    db = tmp_path / "existing.db"
    _clean_env.setenv("DEVHARNESS_DB", str(db))
    open_store().close()  # create it (announced)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        conn = open_store()  # second open: existing, no announcement
    try:
        assert "created NEW EMPTY" not in err.getvalue()
    finally:
        conn.close()


def test_relative_path_resolves_absolute(_clean_env, tmp_path, monkeypatch):
    # a relative DEVHARNESS_DB resolves against cwd — the resolved absolute path is what opens
    monkeypatch.chdir(tmp_path)
    _clean_env.setenv("DEVHARNESS_DB", "rel.db")
    conn = open_store()
    try:
        assert (tmp_path / "rel.db").exists()  # created where the relative path resolved
    finally:
        conn.close()


def test_existing_foreign_db_exits_closed(_clean_env, tmp_path):
    # rev 0.4.13: open_store migrates on connect — adopting an existing non-store would write
    # devharness schema into a foreign database (live: parallax.db in the VPS var/).
    import sqlite3

    foreign = tmp_path / "parallax.db"
    conn = sqlite3.connect(str(foreign))
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    _clean_env.setenv("DEVHARNESS_DB", str(foreign))
    before = foreign.read_bytes()
    with pytest.raises(SystemExit, match="not a devharness event store"):
        open_store()
    assert foreign.read_bytes() == before  # refused BEFORE any write
