"""L4-1: unsandboxed host execution is fail-closed without explicit operator authorization.

A host subprocess (no §S5 sandbox launcher) gives a prompt-injected worker arbitrary host reach the
destructive blocklist + realized-diff scope check cannot contain, so it runs only with
DEVHARNESS_ALLOW_HOST_SHELL=1 (trusted-host opt-in) or a sandbox launcher.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import pytest

from devharness.aci.host_exec import HostExecutionRefused, require_host_execution_authorized
from devharness.aci.shell import ShellActions
from devharness.aci.test_runner import TestRunnerActions


class _WT:
    def __init__(self, path="."):
        self.path = path


def test_authorized_when_env_set(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_ALLOW_HOST_SHELL", "1")
    require_host_execution_authorized("x")  # no raise


def test_refused_without_authorization(monkeypatch):
    monkeypatch.delenv("DEVHARNESS_ALLOW_HOST_SHELL", raising=False)
    with pytest.raises(HostExecutionRefused):
        require_host_execution_authorized("shell command")


def test_shell_refuses_unsandboxed_host_exec(monkeypatch):
    monkeypatch.delenv("DEVHARNESS_ALLOW_HOST_SHELL", raising=False)
    with pytest.raises(HostExecutionRefused):
        ShellActions(worktree=_WT()).run_command("echo hi")


def test_test_runner_refuses_unsandboxed_host_exec(monkeypatch):
    monkeypatch.delenv("DEVHARNESS_ALLOW_HOST_SHELL", raising=False)
    with pytest.raises(HostExecutionRefused):
        TestRunnerActions(worktree=_WT()).run_tests(["echo", "hi"])


def test_shell_runs_on_host_when_authorized(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVHARNESS_ALLOW_HOST_SHELL", "1")
    out = ShellActions(worktree=_WT(str(tmp_path))).run_command("echo authorized")
    assert "authorized" in out["stdout"]


def test_destructive_gate_still_fires_before_the_host_check(monkeypatch):
    # a destructive command is refused by the blocklist gate regardless of host authorization
    monkeypatch.delenv("DEVHARNESS_ALLOW_HOST_SHELL", raising=False)
    from devharness.aci.shell import DestructiveCommandRefused
    with pytest.raises(DestructiveCommandRefused):
        ShellActions(worktree=_WT()).run_command("rm -rf /")
