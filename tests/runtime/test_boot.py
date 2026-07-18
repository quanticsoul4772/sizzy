"""B0.4 boot-check wiring test.

check_projection_rebuild_parity is registered under C5; check_required_gates_registered
passes when its REQUIRED_GATES are present and fails closed when one is missing.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot


def test_parity_registered_under_c5():
    assert "check_projection_rebuild_parity" in boot.registered_check_names()
    assert boot.REQUIRED_GATES["check_projection_rebuild_parity"] == "C5"


def test_required_gates_registered_passes():
    assert boot.check_required_gates_registered() is True


def test_missing_required_gate_fails_closed(monkeypatch):
    monkeypatch.setitem(boot.REQUIRED_GATES, "check_not_wired_yet", "C1")
    with pytest.raises(boot.BootError):
        boot.check_required_gates_registered()
