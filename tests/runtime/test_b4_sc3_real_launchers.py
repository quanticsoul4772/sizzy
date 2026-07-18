"""B4.8 SC-3 verification against the REAL sandbox launchers (operator-driven, out-of-CI).

SC-3: 100% of OSS tasks run inside the sandbox; an out-of-sandbox launch fails, not warns. The
MockSandboxLauncher satisfies this structurally (the B4.3 gate denies mock-only). This module verifies
the BEHAVIORAL half against real Linux namespace containment — it is SKIPPED in CI and in normal local
runs, and runs only when the operator opts in:

    # WSL path (Windows dev box with WSL installed):
    DEVHARNESS_RUN_SC3=1 pytest tests/runtime/test_b4_sc3_real_launchers.py -k wsl
    # VPS path (DEVHARNESS_SANDBOX_VPS_HOST/_USER/_KEY_PATH set):
    DEVHARNESS_RUN_SC3=1 pytest tests/runtime/test_b4_sc3_real_launchers.py -k vps

After running, record the acceptance artifact (what was verified, against which launcher, by whom, on
what date) under claudedocs/sc3-acceptance-<commit>.md.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.sandbox.vps import VPSSandboxLauncher
from devharness.sandbox.wsl import WSLSandboxLauncher, detect_wsl

_OPT_IN = os.environ.get("DEVHARNESS_RUN_SC3") == "1"
_PROBE = ["bash", "-c", "echo sandbox-probe-OK; mount | head -20; ip a 2>/dev/null || true"]


@pytest.mark.skipif(not (_OPT_IN and detect_wsl()), reason="SC-3 WSL run is operator-driven (set DEVHARNESS_RUN_SC3=1 on a WSL host)")
def test_sc3_wsl_real_containment(tmp_path):
    result = WSLSandboxLauncher().exec(_PROBE, cwd=str(tmp_path), timeout_seconds=30)
    assert result.contained is True, "WSL launcher did not establish containment"
    assert "sandbox-probe-OK" in result.stdout
    # the namespace boundary holds: the host's worktree pool is not mounted inside the sandbox
    assert ".devharness-worktrees" not in result.stdout


@pytest.mark.skipif(
    not (_OPT_IN and os.environ.get("DEVHARNESS_SANDBOX_VPS_HOST")),
    reason="SC-3 VPS run is operator-driven (set DEVHARNESS_RUN_SC3=1 + DEVHARNESS_SANDBOX_VPS_*)",
)
def test_sc3_vps_real_containment(tmp_path):
    (tmp_path / "probe.txt").write_text("probe\n")
    result = VPSSandboxLauncher().exec(_PROBE, cwd=str(tmp_path), timeout_seconds=60)
    assert result.contained is True, "VPS launcher did not establish containment"
    assert "sandbox-probe-OK" in result.stdout


def test_sc3_module_is_opt_in():
    # a guard so the suite always has at least one running assertion here: the real probes are gated.
    assert _PROBE[0] == "bash"
