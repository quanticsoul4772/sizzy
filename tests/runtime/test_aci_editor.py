"""B2.3: ACI editor writes only within scope; out-of-scope refused; write_applied emitted."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.aci.editor import EditorActions, ScopeViolation
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.worktree.isolate import Worktree


def _editor(tmp_path, scope=("src/**",)):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    worktree = Worktree("t1", str(tmp_path), str(tmp_path))
    editor = EditorActions(
        worktree=worktree, scope_boundary=list(scope), event_bus=bus, conn=conn, correlation_id="c", task_id="t1"
    )
    return conn, editor


def test_write_within_scope_emits_write_applied(tmp_path):
    conn, editor = _editor(tmp_path)
    editor.write_file("src/main.py", "x = 1\n")
    assert (tmp_path / "src" / "main.py").read_text(encoding="utf-8") == "x = 1\n"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='write_applied'").fetchone()[0] == 1


def test_out_of_scope_write_refused(tmp_path):
    conn, editor = _editor(tmp_path)
    with pytest.raises(ScopeViolation):
        editor.write_file("tests/test_x.py", "y = 2\n")  # tests/ not in src/**
    assert not (tmp_path / "tests" / "test_x.py").exists()
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='write_attempted'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='write_applied'").fetchone()[0] == 0


def test_open_and_read_range(tmp_path):
    conn, editor = _editor(tmp_path, scope=("**",))
    editor.write_file("a.txt", "l1\nl2\nl3\n")
    assert editor.open_file("a.txt") == "l1\nl2\nl3\n"
    assert editor.read_range("a.txt", 1, 2) == "l1\nl2"


def test_append(tmp_path):
    conn, editor = _editor(tmp_path, scope=("**",))
    editor.write_file("a.txt", "one\n")
    editor.append_to_file("a.txt", "two\n")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "one\ntwo\n"
