"""The boot gate (#C4): run_boot_checks actually executes every registered check and fails closed.

Regression for the audit finding that nothing iterated the registry and CALLED the checks — so
"24/24 fail-closed at boot" was an emergent property of per-check unit tests, and the former `_ok`
default would have silently passed an unmapped check.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot


def test_run_boot_checks_passes_clean():
    assert boot.run_boot_checks() is True


def test_unmapped_default_fails_closed_when_called():
    with pytest.raises(boot.BootError):
        boot._unmapped()


def test_run_boot_checks_fails_closed_on_a_failing_check():
    boot.register("C1", "_synthetic_bad", lambda: False)
    try:
        with pytest.raises(boot.BootError):
            boot.run_boot_checks()
    finally:
        del boot._REGISTRY["C1"]["_synthetic_bad"]


def test_run_boot_checks_fails_closed_on_a_raising_check():
    def _boom():
        raise RuntimeError("kaboom")

    boot.register("C1", "_synthetic_raises", _boom)
    try:
        with pytest.raises(boot.BootError):
            boot.run_boot_checks()
    finally:
        del boot._REGISTRY["C1"]["_synthetic_raises"]
