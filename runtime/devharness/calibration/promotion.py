"""Calibrated-trust promotion (B2.8, §S1).

The developer earns/keeps write authority on a task class by demonstrated calibration.
A grant expires (default 7 days); renewal extends it; revocation ends it. Trust state is
a projection of the trust_granted / trust_renewed / trust_revoked events.
"""

import os
import time

import msgspec

from devharness.events.registry import TrustGranted, TrustRenewed, TrustRevoked

DEFAULT_TRUST_EXPIRY_DAYS = 7
_DAY_MILLIS = 24 * 60 * 60 * 1000


class TrustPromotion(msgspec.Struct, frozen=True, kw_only=True):
    role_name: str
    task_class: str
    granted_at_millis: int
    expires_at_millis: int
    brier_at_grant: float
    granted_by: str
    schema_version: int = 1


def _now(now_millis):
    return (now_millis or (lambda: int(time.time() * 1000)))()


def _expiry_days() -> int:
    try:
        return int(os.environ.get("DEVHARNESS_TRUST_EXPIRY_DAYS", DEFAULT_TRUST_EXPIRY_DAYS))
    except ValueError:
        return DEFAULT_TRUST_EXPIRY_DAYS


def grant(role_name, task_class, brier, granted_by, conn, event_bus, *, now_millis=None, expiry_days=None) -> TrustPromotion:
    granted_at = _now(now_millis)
    expires_at = granted_at + (expiry_days if expiry_days is not None else _expiry_days()) * _DAY_MILLIS
    event_bus.emit_sync(
        "trust_granted",
        msgspec.to_builtins(TrustGranted(
            role_name=role_name, task_class=task_class, brier_at_grant=float(brier),
            granted_at_millis=granted_at, expires_at_millis=expires_at, granted_by=granted_by,
            correlation_id=f"trust-{role_name}-{task_class}",
        )),
        correlation_id=f"trust-{role_name}-{task_class}",
    )
    return TrustPromotion(
        role_name=role_name, task_class=task_class, granted_at_millis=granted_at,
        expires_at_millis=expires_at, brier_at_grant=float(brier), granted_by=granted_by,
    )


def renew(role_name, task_class, brier, renewed_by, conn, event_bus, *, now_millis=None, expiry_days=None) -> int:
    renewed_at = _now(now_millis)
    new_expires_at = renewed_at + (expiry_days if expiry_days is not None else _expiry_days()) * _DAY_MILLIS
    event_bus.emit_sync(
        "trust_renewed",
        msgspec.to_builtins(TrustRenewed(
            role_name=role_name, task_class=task_class, brier_at_renewal=float(brier),
            renewed_at_millis=renewed_at, new_expires_at_millis=new_expires_at, renewed_by=renewed_by,
            correlation_id=f"trust-{role_name}-{task_class}",
        )),
        correlation_id=f"trust-{role_name}-{task_class}",
    )
    return new_expires_at


def revoke(role_name, task_class, reason, revoked_by, conn, event_bus, *, now_millis=None) -> None:
    event_bus.emit_sync(
        "trust_revoked",
        msgspec.to_builtins(TrustRevoked(
            role_name=role_name, task_class=task_class, reason=reason,
            revoked_at_millis=_now(now_millis), revoked_by=revoked_by,
            correlation_id=f"trust-{role_name}-{task_class}",
        )),
        correlation_id=f"trust-{role_name}-{task_class}",
    )


def has_active_trust(role_name, task_class, conn, *, now_millis=None) -> bool:
    now = _now(now_millis)
    row = conn.execute(
        "SELECT expires_at_millis, revoked_at_millis FROM proj_trust_grants "
        "WHERE role_name = ? AND task_class = ? ORDER BY granted_at_millis DESC, grant_row_id DESC LIMIT 1",
        (role_name, task_class),
    ).fetchone()
    if row is None:
        return False
    expires_at, revoked_at = row
    return revoked_at is None and expires_at > now
