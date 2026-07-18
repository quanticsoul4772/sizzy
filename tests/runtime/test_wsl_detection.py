"""B4.2.5: detect_wsl — True only on Windows with wsl.exe + an installed distro."""

import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.sandbox import wsl


def _patch(monkeypatch, *, platform="win32", which="C:/wsl.exe", distros="Ubuntu\n", rc=0, raises=None):
    monkeypatch.setattr(wsl.sys, "platform", platform)
    monkeypatch.setattr(wsl.shutil, "which", lambda name: which)

    def fake_run(*a, **k):
        if raises:
            raise raises
        return types.SimpleNamespace(returncode=rc, stdout=distros, stderr="")
    monkeypatch.setattr(wsl.subprocess, "run", fake_run)


def test_true_when_wsl_and_distro_present(monkeypatch):
    _patch(monkeypatch)
    assert wsl.detect_wsl() is True


def test_false_off_windows(monkeypatch):
    _patch(monkeypatch, platform="linux")
    assert wsl.detect_wsl() is False


def test_false_when_wsl_exe_missing(monkeypatch):
    _patch(monkeypatch, which=None)
    assert wsl.detect_wsl() is False


def test_false_when_no_distro(monkeypatch):
    _patch(monkeypatch, distros="\n")
    assert wsl.detect_wsl() is False


def test_false_when_probe_raises(monkeypatch):
    _patch(monkeypatch, raises=subprocess.SubprocessError())
    assert wsl.detect_wsl() is False
