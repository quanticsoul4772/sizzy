"""Track 1d behavioral: the seccomp filter actually blocks a denied syscall on the real WSL launcher.

Gated like the SC-3 real-launcher tests (WSL/operator-driven) — `test_seccomp.py` covers the denylist +
BPF structure; this is the *runtime* evidence that the filter denies (EPERM) a syscall that succeeds
unprivileged WITHOUT it, and that an allowed command still runs. Run on a WSL host with
DEVHARNESS_RUN_SECCOMP=1 (or DEVHARNESS_RUN_SC3=1).
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.sandbox.wsl import WSLSandboxLauncher, detect_wsl

_OPT_IN = os.environ.get("DEVHARNESS_RUN_SECCOMP") or os.environ.get("DEVHARNESS_RUN_SC3")


@pytest.mark.skipif(
    not (_OPT_IN and detect_wsl()),
    reason="seccomp behavioral run is WSL/operator-driven (set DEVHARNESS_RUN_SECCOMP=1 on a WSL host)",
)
def test_seccomp_blocks_a_denied_syscall_on_real_wsl(tmp_path):
    launcher = WSLSandboxLauncher()

    # 1. an ALLOWED command runs to completion inside the sandbox
    ok = launcher.exec(["bash", "-c", "echo allowed-ok"], cwd=str(tmp_path), timeout_seconds=60)
    assert ok.returncode == 0 and ok.contained and "allowed-ok" in ok.stdout

    # 2. the seccomp filter is actually loaded (mode 2 = SECCOMP_MODE_FILTER)
    mode = launcher.exec(["bash", "-c", "grep '^Seccomp:' /proc/self/status"], cwd=str(tmp_path), timeout_seconds=60)
    assert mode.contained and mode.stdout.split(":")[-1].strip() == "2", f"seccomp not in filter mode: {mode.stdout!r}"

    # 3. a DENIED syscall is blocked. `unshare --user` SUCCEEDS unprivileged without the filter, so a failure
    #    here is proof the seccomp block (not a privilege check) denied unshare(272).
    denied = launcher.exec(["bash", "-c", "unshare --user true; echo rc=$?"], cwd=str(tmp_path), timeout_seconds=60)
    assert denied.contained
    assert "Operation not permitted" in denied.stdout or "rc=1" in denied.stdout, f"unshare not blocked: {denied.stdout!r}"
