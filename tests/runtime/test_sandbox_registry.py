"""B4.2.5: SANDBOX_LAUNCHERS registry + resolve_launcher selection."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.sandbox import registry
from devharness.sandbox.base import SandboxContainmentError
from devharness.sandbox.mock import MockSandboxLauncher
from devharness.sandbox.registry import SANDBOX_LAUNCHERS, UnknownLauncherError, resolve_launcher
from devharness.sandbox.vps import VPSSandboxLauncher
from devharness.sandbox.wsl import WSLSandboxLauncher


def test_registry_prepopulated():
    assert set(SANDBOX_LAUNCHERS) == {"mock", "wsl", "vps"}


def test_preferred_mock():
    assert isinstance(resolve_launcher(preferred="mock"), MockSandboxLauncher)


def test_unknown_preferred_raises():
    with pytest.raises(UnknownLauncherError):
        resolve_launcher(preferred="nope")


def test_auto_selects_wsl_when_present(monkeypatch):
    monkeypatch.setattr(registry, "detect_wsl", lambda: True)
    assert isinstance(resolve_launcher(), WSLSandboxLauncher)


def test_auto_selects_mock_when_no_wsl(monkeypatch):
    monkeypatch.setattr(registry, "detect_wsl", lambda: False)
    assert isinstance(resolve_launcher(), MockSandboxLauncher)


def test_vps_never_auto_selected(monkeypatch):
    monkeypatch.setattr(registry, "detect_wsl", lambda: False)
    assert not isinstance(resolve_launcher(), VPSSandboxLauncher)


def test_preferred_vps_returns_even_without_config(monkeypatch):
    # the registry returns the launcher; containment fails closed only at exec
    monkeypatch.delenv("DEVHARNESS_SANDBOX_VPS_HOST", raising=False)
    launcher = resolve_launcher(preferred="vps")
    assert isinstance(launcher, VPSSandboxLauncher)
    with pytest.raises(SandboxContainmentError):
        launcher.exec(["echo", "hi"], cwd="/work")
