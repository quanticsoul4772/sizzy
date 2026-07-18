"""B4.2.5: MockSandboxLauncher fail-closed (contained=False); accepts the timeout arg."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.sandbox.mock import MockSandboxLauncher


def test_fail_closed_result():
    r = MockSandboxLauncher().exec(["echo", "hi"], cwd="/tmp")
    assert r.contained is False
    assert r.returncode == -1
    assert "no real containment" in r.stderr


def test_honors_timeout_argument():
    # the mock does not run anything, but the signature accepts a wall-clock limit
    r = MockSandboxLauncher().exec(["sleep", "999"], cwd="/tmp", timeout_seconds=5)
    assert r.contained is False
