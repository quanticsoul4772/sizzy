"""B4.1: SPDX license allowlist — default set, env override, case-insensitive."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.oss.license_allowlist import DEFAULT_ALLOWED_LICENSES, allowed_licenses, is_license_allowed


def test_default_set():
    assert DEFAULT_ALLOWED_LICENSES == frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0"})


def test_allowed_and_disallowed():
    assert is_license_allowed("MIT") is True
    assert is_license_allowed("Apache-2.0") is True
    assert is_license_allowed("GPL-3.0") is False  # copyleft, not on the default allowlist
    assert is_license_allowed("") is False


def test_case_insensitive():
    assert is_license_allowed("mit") is True
    assert is_license_allowed("apache-2.0") is True
    assert is_license_allowed("  MIT  ") is True


def test_env_override(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_ALLOWED_LICENSES", "GPL-3.0, LGPL-3.0")
    assert allowed_licenses() == frozenset({"GPL-3.0", "LGPL-3.0"})
    assert is_license_allowed("GPL-3.0") is True
    assert is_license_allowed("MIT") is False  # the override replaces the default
