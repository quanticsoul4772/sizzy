"""SPDX license allowlist (B4.1, §S5 intake hardening).

An OSS contribution is refused unless the upstream repo's license is on the allowlist. The
default set is permissive/weak-copyleft licenses; the operator may override via the env var
``DEVHARNESS_OSS_ALLOWED_LICENSES`` (comma-separated SPDX identifiers).
"""

import os

DEFAULT_ALLOWED_LICENSES = frozenset({
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0",
})


def allowed_licenses() -> frozenset:
    """The active allowlist: the env override (if set) else the default set."""
    override = os.environ.get("DEVHARNESS_OSS_ALLOWED_LICENSES")
    if override:
        return frozenset(part.strip() for part in override.split(",") if part.strip())
    return DEFAULT_ALLOWED_LICENSES


def is_license_allowed(license_spdx: str) -> bool:
    """True iff the SPDX identifier (case-insensitive) is on the active allowlist."""
    if not license_spdx:
        return False
    target = license_spdx.strip().lower()
    return any(target == allowed.lower() for allowed in allowed_licenses())
