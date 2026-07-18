"""B4.2.5: WSLSandboxLauncher — unshare wrapper, path translation, containment error."""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.sandbox import wsl
from devharness.sandbox.base import SandboxContainmentError
from devharness.sandbox.wsl import WSLSandboxLauncher, to_wsl_path


def test_path_translation():
    assert to_wsl_path(r"C:\Development\Projects\x") == "/mnt/c/Development/Projects/x"
    assert to_wsl_path("D:/data/repo") == "/mnt/d/data/repo"


def test_exec_confines_fs_and_runs_command(monkeypatch):
    captured = {}

    def fake_run(args, **k):
        captured["args"] = args  # the real inner script emits the sentinel on stderr from inside the namespace
        return types.SimpleNamespace(returncode=0, stdout="ok", stderr=wsl._CONTAINED_SENTINEL + "\n")
    monkeypatch.setattr(wsl.subprocess, "run", fake_run)

    r = WSLSandboxLauncher().exec(["python", "-c", "print(1)"], cwd=r"C:\Development\repo", timeout_seconds=15)
    assert r.contained is True and r.returncode == 0
    assert wsl._CONTAINED_SENTINEL not in r.stderr  # F6: sentinel stripped from the surfaced stderr
    args = captured["args"]
    assert wsl._CONTAINED_SENTINEL in args[-1]  # the inner script emits it before exec
    assert args[0] == "wsl.exe" and "unshare" in args
    assert "--map-root-user" in args and "--fork" in args  # mount ops need mapped-root; --pid needs --fork
    assert args[-3:-1] == ["bash", "-c"]
    inner = args[-1]
    # worktree confinement (Track 1c): pivot_root into a fresh root with only the system dirs + the worktree
    # bound at /work; the command runs in /work, with /home, /mnt/c, ~/.ssh gone.
    assert "mount --rbind /mnt/c/Development/repo $NR/work" in inner  # worktree -> /work (rbind: /usr-quirk)
    assert "pivot_root . .oldroot" in inner and "umount -l /.oldroot" in inner
    assert "cd /work" in inner
    assert "mount -t proc proc $NR/proc" in inner  # a fresh /proc for the pid namespace
    assert "exec python3 -c" in inner  # the command runs under the seccomp installer (Track 1d)
    assert inner.rstrip().endswith("python -c 'print(1)'")  # the real command is the final arg
    assert "--cd" not in args  # no longer runs at /mnt/c


def test_containment_error_when_wsl_missing(monkeypatch):
    def fake_run(args, **k):
        raise FileNotFoundError("wsl.exe")
    monkeypatch.setattr(wsl.subprocess, "run", fake_run)
    with pytest.raises(SandboxContainmentError):
        WSLSandboxLauncher().exec(["echo", "hi"], cwd=r"C:\x")


def test_timeout_without_sentinel_is_not_contained(monkeypatch):
    # audit F1: a timeout whose partial stderr lacks the containment sentinel (e.g. it fired during
    # startup/pivot, before the command entered containment) must report contained=False, not a hopeful True.
    import subprocess

    def fake_run(args, **k):
        raise subprocess.TimeoutExpired(cmd=args, timeout=1, stderr="")
    monkeypatch.setattr(wsl.subprocess, "run", fake_run)
    r = WSLSandboxLauncher().exec(["sleep", "999"], cwd=r"C:\x", timeout_seconds=1)
    assert r.contained is False and r.returncode == 124


def test_timeout_after_sentinel_is_contained(monkeypatch):
    # a timeout AFTER the sentinel was emitted (the command entered containment) is evidence-backed True
    import subprocess

    def fake_run(args, **k):
        raise subprocess.TimeoutExpired(cmd=args, timeout=1, stderr=wsl._CONTAINED_SENTINEL + "\n")
    monkeypatch.setattr(wsl.subprocess, "run", fake_run)
    r = WSLSandboxLauncher().exec(["sleep", "999"], cwd=r"C:\x", timeout_seconds=1)
    assert r.contained is True and r.returncode == 124


def test_contained_is_false_without_the_sentinel(monkeypatch):  # F6
    def fake_run(args, **k):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="mount: operation not permitted")
    monkeypatch.setattr(wsl.subprocess, "run", fake_run)
    r = WSLSandboxLauncher().exec(["echo", "hi"], cwd=r"C:\x")
    assert r.contained is False  # the mount/bind/tmpfs setup did not run; never claim containment
