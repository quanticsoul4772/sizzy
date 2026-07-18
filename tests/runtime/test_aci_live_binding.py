"""B2.7: the live devharness-aci MCP server + tool calls reach the surfaces."""

import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.aci.editor import EditorActions
from devharness.aci.server import ACI_SERVER_NAME, build_aci_server, call_tool, make_aci_mcp_server
from devharness.aci.shell import ShellActions
from devharness.aci.test_runner import TestRunnerActions
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.worktree.isolate import Worktree


def _surfaces(tmp_path):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    worktree = Worktree("t1", str(tmp_path), str(tmp_path))
    editor = EditorActions(worktree=worktree, scope_boundary=["**"], event_bus=EventBus(conn), conn=conn, correlation_id="c", task_id="t1")
    return editor, ShellActions(worktree=worktree), TestRunnerActions(worktree=worktree)


def test_make_aci_mcp_server_is_a_live_sdk_server(tmp_path):
    editor, shell, test_runner = _surfaces(tmp_path)
    server = make_aci_mcp_server(editor, shell, test_runner)
    # a live in-process Agent-SDK MCP server config (type='sdk' with a server instance)
    assert server["type"] == "sdk"
    assert server["name"] == ACI_SERVER_NAME
    assert server["instance"] is not None


def test_tool_call_reaches_editor_surface(tmp_path):
    editor, shell, test_runner = _surfaces(tmp_path)
    descriptor = build_aci_server(editor, shell, test_runner)
    call_tool(descriptor, "write_file", rel_path="src/main.py", content="x = 1\n")
    assert (tmp_path / "src" / "main.py").read_text(encoding="utf-8") == "x = 1\n"


def test_tool_call_reaches_test_runner_surface(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})())
    editor, shell, test_runner = _surfaces(tmp_path)
    descriptor = build_aci_server(editor, shell, test_runner)
    result = call_tool(descriptor, "run_tests")
    assert result["passed"] is True
