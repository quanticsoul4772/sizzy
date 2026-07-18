"""#C6/#1a: the live driver wires the §S5 sandbox routing (it was dormant — no driver ever set it).

run_developer now constructs a SandboxLauncher and threads it into the DeveloperRole, but ONLY when the
operator opts in via DEVHARNESS_SANDBOX_PREFERRED — host by default, because the mock launcher is
fail-closed (its exec never runs the command) and must never be the silent default. The role-level
routing (shell/test-runner through the launcher) is covered by test_sandbox_routing.py.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime"))
sys.path.insert(0, str(REPO / "scripts"))

from devharness.sandbox.mock import MockSandboxLauncher
from run_developer import _sandbox_launcher


def test_defaults_to_host_when_not_opted_in(monkeypatch):
    monkeypatch.delenv("DEVHARNESS_SANDBOX_PREFERRED", raising=False)
    assert _sandbox_launcher() is None  # no silent fail-closed mock on the host path


def test_resolves_a_launcher_when_opted_in(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_SANDBOX_PREFERRED", "mock")
    assert isinstance(_sandbox_launcher(), MockSandboxLauncher)
