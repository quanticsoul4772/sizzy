"""WSLSandboxLauncher + WSL detection (B4.2.5; Windows-drive confinement Track-1b 2026-06-25).

Runs the command in user/network/pid/mount/uts namespaces via WSL. **Windows-drive confinement** (§S4
residual): the worktree lives on `/mnt/c` (a 9p drvfs mount), which the mount namespace would otherwise
inherit — exposing the whole Windows `C:` drive. So inside the namespace the launcher bind-mounts the
worktree to a WSL-FS path (it stays writable in-place — the bind holds an independent reference), then
overlays an empty tmpfs on `/mnt`, hiding every Windows drive. `--map-root-user` is needed for the mount ops
(the mapped root = the unprivileged WSL user outside); `--fork` is required with `--pid` (else the first
`fork()` fails `Cannot allocate memory`).

WORKTREE CONFINEMENT (Track 1c): the launcher `pivot_root`s into a fresh root that contains ONLY the system
dirs needed to run the command (`/usr`,`/bin`,`/lib`,`/lib64`,`/sbin`,`/etc`, a `/proc`, a `/dev`, a tmpfs
`/tmp`) plus the worktree bound at `/work`. After the pivot, `/home`, `/mnt/c` (all Windows drives), `~/.ssh`,
`/root`, and every other project are GONE — the command sees only its worktree + the read-only-by-permission
system dirs. `/usr` is a separate ext4 mount on WSL2, so the binds use `--rbind` (plain `--bind` fails rc=32).
`--map-root-user` is needed for the mount/pivot ops (mapped root = the unprivileged WSL user outside, so the
command cannot write the bound system dirs); `--fork` is required with `--pid`. seccomp is the remaining
hardening. Verified on real WSL: rootfs after pivot = system dirs + /work only; /home, /mnt/c, /root CONFINED;
worktree WRITABLE; python3 runs; NET-BLOCKED.
"""

import shlex
import shutil
import subprocess
import sys

from devharness.sandbox.base import SandboxContainmentError, SandboxLauncher, SandboxResult
from devharness.sandbox.confine import pivot_setup
from devharness.sandbox.seccomp import seccomp_exec

# Emitted on stderr from INSIDE the namespace, so contained=True is evidence (the mounts ran), not a claim.
_CONTAINED_SENTINEL = "__devharness_sandbox_contained__"
_UNSHARE = ["unshare", "--user", "--map-root-user", "--net", "--pid", "--mount", "--uts", "--fork", "--"]


def detect_wsl() -> bool:
    """True iff WSL is available: Windows host + wsl.exe in PATH + >=1 installed distribution."""
    if sys.platform != "win32":
        return False
    if shutil.which("wsl.exe") is None:
        return False
    try:
        proc = subprocess.run(["wsl.exe", "-l", "-q"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    # WSL emits UTF-16 with NULs on some hosts; strip them before checking for a distro line
    distros = [line.strip() for line in (proc.stdout or "").replace("\x00", "").splitlines() if line.strip()]
    return proc.returncode == 0 and len(distros) >= 1


def to_wsl_path(win_path: str) -> str:
    """Translate a Windows path (C:\\Development\\x) to its WSL mount form (/mnt/c/Development/x)."""
    p = win_path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        return f"/mnt/{p[0].lower()}{p[2:]}"
    return p


class WSLSandboxLauncher(SandboxLauncher):
    name = "wsl"

    def _inner_script(self, wsl_cwd: str, command: list[str]) -> str:
        cmd = " ".join(shlex.quote(c) for c in command)
        # pivot_root worktree confinement (shared, hardened recipe) + the command under the seccomp filter.
        return pivot_setup(shlex.quote(wsl_cwd), _CONTAINED_SENTINEL) + f"exec {seccomp_exec(cmd)}"

    def exec(self, command: list[str], cwd: str, timeout_seconds: int = 30) -> SandboxResult:
        wsl_cwd = to_wsl_path(cwd)
        args = ["wsl.exe", "-e", *_UNSHARE, "bash", "-c", self._inner_script(wsl_cwd, command)]
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout_seconds)
        except FileNotFoundError as e:
            raise SandboxContainmentError(f"wsl.exe unavailable: {e}") from e
        except subprocess.TimeoutExpired as e:
            # contained is evidence-based even on timeout (audit F1): True only if the sentinel was already
            # emitted (the pivot/mounts ran before the command). A timeout DURING startup/pivot — before the
            # command entered containment — must report contained=False, not a hopeful claim.
            partial = e.stderr or ""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", "replace")
            return SandboxResult(returncode=124, stdout="", stderr="sandbox: command timed out",
                                 contained=_CONTAINED_SENTINEL in partial)
        raw_err = proc.stderr or ""
        contained = _CONTAINED_SENTINEL in raw_err  # evidence: the mount/bind/tmpfs ran before the command
        stderr = raw_err.replace(_CONTAINED_SENTINEL + "\n", "").replace(_CONTAINED_SENTINEL, "")
        return SandboxResult(
            returncode=proc.returncode,
            stdout=(proc.stdout or "")[-4000:],
            stderr=stderr[-4000:],
            contained=contained,
        )
