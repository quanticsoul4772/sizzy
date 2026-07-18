"""B4.2: three C1 OSS-gate boot-checks graduate to real bodies; ledger 23 real / 1 stub."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot


def test_three_path_loc_checks_have_real_bodies():
    for name in ("workflow_guard", "secret_guard", "scope_guard"):
        fn = boot._REGISTRY["C1"][name]
        assert fn is not boot._unmapped, f"{name} boot-check is still a stub"
        assert fn() is True  # the real body passes (the gate enforces its known-bad)


# the sandbox-stub + 23/1-ledger assertions moved to test_b4_3_boot_checks (sandbox graduated in B4.3)
