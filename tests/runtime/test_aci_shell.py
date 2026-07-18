"""B2.3: ACI shell refuses destructive commands; allows safe ones."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.aci.shell import DestructiveCommandRefused, ShellActions
from devharness.gates.destructive import BLOCKLIST
from devharness.worktree.isolate import Worktree


class _Proc:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = "out"
        self.stderr = "err"


def _shell(tmp_path):
    return ShellActions(worktree=Worktree("t", str(tmp_path), str(tmp_path)))


@pytest.mark.parametrize("pattern", BLOCKLIST)
def test_refuses_each_destructive_pattern(tmp_path, pattern):
    with pytest.raises(DestructiveCommandRefused) as exc:
        _shell(tmp_path).run_command(f"echo start && {pattern} && echo end")
    assert pattern in exc.value.deny.reason


def test_allows_safe_command(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0))
    result = _shell(tmp_path).run_command("git status")
    assert result["returncode"] == 0
    assert result["command"] == "git status"
