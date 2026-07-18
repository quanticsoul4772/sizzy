"""B4.3: the 4th C1 OSS-gate boot-check graduates; ledger 23 real / 0 stub (all bodies real)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot


def test_sandbox_check_has_real_body():
    fn = boot._REGISTRY["C1"]["sandbox"]
    assert fn is not boot._unmapped
    assert fn() is True  # the real body passes (the gate denies its mock-only known-bad)


def test_all_four_oss_gate_checks_real():
    for name in ("workflow_guard", "secret_guard", "scope_guard", "sandbox"):
        assert boot._REGISTRY["C1"][name] is not boot._unmapped


def test_ledger_23_real_0_stub():
    real = sum(1 for checks in boot._REGISTRY.values() for fn in checks.values() if fn is not boot._unmapped)
    stub = sum(1 for checks in boot._REGISTRY.values() for fn in checks.values() if fn is boot._unmapped)
    assert real == len(boot.registered_check_names()) and stub == 0
    assert len(boot.registered_check_names()) == len(boot.REQUIRED_GATES)  # Inv 18: the 23 names unchanged
