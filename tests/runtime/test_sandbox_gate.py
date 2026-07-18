"""B4.3: sandbox gate — denies when only the mock resolves; override + real launchers allow."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.gates.base import GateDeny, GateOk
from devharness.gates import sandbox as sandbox_mod
from devharness.gates.sandbox import SandboxGate
from devharness.sandbox import registry as sandbox_registry


def _g():
    return SandboxGate()


def test_mock_only_no_override_denies(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    r = _g().check({})
    assert isinstance(r, GateDeny) and r.reason.startswith("sandbox_unavailable")
    assert r.evidence["resolved_launcher"] == "mock"
    assert set(r.evidence["available_launchers"]) == {"mock", "wsl", "vps"}


def test_mock_only_with_override_allows(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    r = _g().check({"sandbox_override": True})
    assert isinstance(r, GateOk) and r.reason == "sandbox_unavailable_with_override"
    assert r.evidence["resolved_launcher"] == "mock"


def test_wsl_available_allows(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: True)
    r = _g().check({})
    assert isinstance(r, GateOk) and r.reason == "sandbox_available"
    assert r.evidence["resolved_launcher"] == "wsl"


def test_preferred_vps_allows():
    # resolve_launcher(preferred="vps") returns the VPS launcher regardless of host/config; the gate
    # is structural (no exec), so it passes — config is only consulted when the launcher exec()s.
    r = _g().check({"sandbox_launcher_preferred": "vps"})
    assert isinstance(r, GateOk) and r.evidence["resolved_launcher"] == "vps"
