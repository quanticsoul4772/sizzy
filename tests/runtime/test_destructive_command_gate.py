"""B2.1: DestructiveCommandGate allows safe commands, denies blocklist patterns."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.gates.base import GateDeny, GateOk
from devharness.gates.destructive import BLOCKLIST, DestructiveCommandGate


@pytest.mark.parametrize("cmd", ["ls -la", "git status", "pytest -q", "git commit -m 'x'", "git push origin main"])
def test_allows_safe_commands(cmd):
    assert isinstance(DestructiveCommandGate().check({"command_string": cmd}), GateOk)


@pytest.mark.parametrize("pattern", BLOCKLIST)
def test_denies_each_blocklist_pattern(pattern):
    deny = DestructiveCommandGate().check({"command_string": f"do something then {pattern} now"})
    assert isinstance(deny, GateDeny)
    assert pattern in deny.reason
    assert deny.purpose.startswith("Destructive-command gate")
    assert deny.fix


def test_empty_command_passes():
    assert isinstance(DestructiveCommandGate().check({}), GateOk)
