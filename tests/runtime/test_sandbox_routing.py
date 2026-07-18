"""#1a (rev 0.3.24): the ACI shell + test-runner route through a §S5 SandboxLauncher when one is
provided (opt-in, for out-of-worktree host containment of the local developer); default is host
execution (back-compat). This is the first wiring of SandboxLauncher.exec into command execution."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.aci.shell import ShellActions
from devharness.aci.test_runner import TestRunnerActions
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.roles.developer import DeveloperRole
from devharness.sandbox.base import SandboxResult


class _Worktree:
    def __init__(self, path):
        self.path = path


class _RecordingLauncher:
    def __init__(self):
        self.calls = []

    def exec(self, command, cwd, timeout_seconds=30):
        self.calls.append((command, cwd))
        return SandboxResult(returncode=0, stdout="sandboxed-out", stderr="", contained=True)


def test_shell_routes_through_sandbox_when_set(tmp_path):
    launcher = _RecordingLauncher()
    shell = ShellActions(worktree=_Worktree(str(tmp_path)), sandbox_launcher=launcher)
    out = shell.run_command("echo hi")
    assert launcher.calls == [(["sh", "-c", "echo hi"], str(tmp_path))]
    assert out["returncode"] == 0 and out["stdout"] == "sandboxed-out" and out["contained"] is True


def test_shell_runs_on_host_when_no_launcher(tmp_path):
    shell = ShellActions(worktree=_Worktree(str(tmp_path)))
    out = shell.run_command("echo hi")
    assert out["contained"] is False
    assert "hi" in out["stdout"]


def test_test_runner_routes_through_sandbox_when_set(tmp_path):
    launcher = _RecordingLauncher()
    runner = TestRunnerActions(worktree=_Worktree(str(tmp_path)), sandbox_launcher=launcher)
    out = runner.run_tests(["pytest", "-q"])
    assert launcher.calls == [(["pytest", "-q"], str(tmp_path))]
    assert out["passed"] is True and out["contained"] is True


def test_developer_threads_launcher_into_aci():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    launcher = _RecordingLauncher()
    dev = DeveloperRole.spawn(conn=conn, correlation_id="c", event_bus=EventBus(conn), sandbox_launcher=launcher)
    _editor, shell, runner = dev.build_aci(_Worktree("/wt"), ["**"], "c", "t0")
    assert shell.sandbox_launcher is launcher
    assert runner.sandbox_launcher is launcher
