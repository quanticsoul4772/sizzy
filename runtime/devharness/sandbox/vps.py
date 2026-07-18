"""VPSSandboxLauncher (B4.2.5) — remote namespace isolation on an Ubuntu VPS over SSH.

Configuration comes from env vars (DEVHARNESS_SANDBOX_VPS_HOST / _USER / _KEY_PATH), following the
sibling-project SSH/credentials pattern (cross-reference agent-harness / sibling-agent — do not
invent a new credential store). Never auto-selected (avoids accidental network calls in dev); opt in
via resolve_launcher(preferred="vps"). Used in the B4.8 acceptance pass for production-like SC-3.
"""

import os
import shlex
import subprocess

from devharness.sandbox.base import SandboxContainmentError, SandboxLauncher, SandboxResult
from devharness.sandbox.confine import pivot_setup
from devharness.sandbox.seccomp import seccomp_exec

_REMOTE_DIR = "/tmp/devharness-sandbox"
# A dedicated unprivileged sandbox user the command runs AS (verified on the VPS 2026-06-25).
_SANDBOX_USER = os.environ.get("DEVHARNESS_SANDBOX_VPS_SBUSER", "devharness-sb")
# Emitted on stderr from INSIDE the namespace+setpriv, so contained=True is evidence, not an assertion.
_CONTAINED_SENTINEL = "__devharness_sandbox_contained__"


class VPSSandboxLauncher(SandboxLauncher):
    name = "vps"

    def __init__(self, host=None, user=None, key_path=None):
        # read config at construction but do NOT raise on missing — the registry returns the launcher
        # even with incomplete config; exec() is where containment fails closed.
        self.host = host or os.environ.get("DEVHARNESS_SANDBOX_VPS_HOST")
        self.user = user or os.environ.get("DEVHARNESS_SANDBOX_VPS_USER")
        self.key_path = key_path or os.environ.get("DEVHARNESS_SANDBOX_VPS_KEY_PATH")

    def _ssh_opts(self) -> list[str]:
        return ["-i", self.key_path, "-o", "StrictHostKeyChecking=accept-new"]

    def _remote_script(self, command: list[str]) -> str:
        sb = shlex.quote(_SANDBOX_USER)  # never interpolate an env value into a shell unquoted
        cmd = " ".join(shlex.quote(c) for c in command)
        # Inside the (root) namespace: the shared pivot_root confinement (worktree -> /work, minimal /dev,
        # masked /proc), then `setpriv` drops to the unprivileged sandbox user and runs the command under the
        # seccomp filter in /work. After the pivot, the VPS rootfs (/home, other users' keys) is GONE.
        pivot = pivot_setup(_REMOTE_DIR, _CONTAINED_SENTINEL) + (
            f"exec setpriv --reuid {sb} --regid {sb} --clear-groups -- {seccomp_exec(cmd)}"
        )
        # Transport: the worktree arrives as a tar stream on stdin (no rsync — the dev host may lack it).
        # `sudo unshare` makes the namespaces as root (Ubuntu 24.04 AppArmor blocks unprivileged user+mount);
        # the pivot + setpriv run inside it.
        return (
            f"set -e; sudo rm -rf {_REMOTE_DIR}; mkdir -p {_REMOTE_DIR}; tar -x -C {_REMOTE_DIR}; "
            f"sudo chown -R {sb}:{sb} {_REMOTE_DIR}; "
            f"sudo unshare --net --pid --mount --uts --fork -- sh -c {shlex.quote(pivot)}"
        )

    def exec(self, command: list[str], cwd: str, timeout_seconds: int = 30) -> SandboxResult:
        if not (self.host and self.user and self.key_path):
            raise SandboxContainmentError(
                "VPS config incomplete: set DEVHARNESS_SANDBOX_VPS_{HOST,USER,KEY_PATH}"
            )
        target = f"{self.user}@{self.host}"
        ssh = ["ssh", *self._ssh_opts(), "--", target, self._remote_script(command)]  # -- guards a `-`-host
        tar = None
        try:
            tar = subprocess.Popen(["tar", "-c", "-C", cwd, "."], stdout=subprocess.PIPE)
            proc = subprocess.run(ssh, stdin=tar.stdout, capture_output=True, text=True, timeout=timeout_seconds)
        except FileNotFoundError as e:
            raise SandboxContainmentError(f"ssh/tar unavailable: {e}") from e
        except subprocess.TimeoutExpired as e:
            # contained is evidence-based even on timeout (audit F1): True only if the sentinel was already
            # emitted (the namespace+setpriv ran before the command). A timeout during connect/extract/pivot
            # — before the command entered containment — reports contained=False.
            partial = e.stderr or ""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", "replace")
            return SandboxResult(returncode=124, stdout="", stderr="sandbox: command timed out",
                                 contained=_CONTAINED_SENTINEL in partial)
        finally:
            if tar is not None and tar.stdout is not None:
                tar.stdout.close()
                tar.wait()
        raw_err = proc.stderr or ""
        contained = _CONTAINED_SENTINEL in raw_err  # evidence: the namespace+setpriv ran before the command
        stderr = raw_err.replace(_CONTAINED_SENTINEL + "\n", "").replace(_CONTAINED_SENTINEL, "")
        return SandboxResult(
            returncode=proc.returncode,
            stdout=(proc.stdout or "")[-4000:],
            stderr=stderr[-4000:],
            contained=contained,
        )
