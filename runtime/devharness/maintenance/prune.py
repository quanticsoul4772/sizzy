"""Operator-authorized prune — the delete path the advisory PruneCycle (§S6) deliberately lacks.

Maintenance cycles never delete data (the §S6 invariant); the PruneCycle only *reports* expired trust
grants. This is the separate, operator-authorized companion that actually removes them: it emits one
``trust_grant_pruned`` event per expired grant (the event-sourced delete — the handler removes the
projection row, reproducible on replay). It REQUIRES an ``authorized_by`` + ``reason`` — the operator
authorization — and only ever touches EXPIRED, non-revoked grants (already invalid at point-of-use, so
this is storage tidiness, never a correctness/security change).
"""

import time

import msgspec

from devharness.events.registry import TrustGrantPruned


def _now(now_millis):
    return (now_millis or (lambda: int(time.time() * 1000)))()


def expired_trust_grants(conn, *, at_millis) -> list:
    """The expired, non-revoked trust grants — what an authorized prune would remove (and what the
    advisory PruneCycle counts). Each row is (grant_row_id, role_name, task_class, granted_at_millis);
    the grant_row_id (the projection PK) is what the prune deletes by — the natural key (role, class,
    granted_at) is not unique (two grants can share the same millisecond)."""
    return conn.execute(
        "SELECT grant_row_id, role_name, task_class, granted_at_millis FROM proj_trust_grants "
        "WHERE revoked_at_millis IS NULL AND expires_at_millis < ? ORDER BY grant_row_id",
        (at_millis,),
    ).fetchall()


def prune_expired_trust_grants(conn, event_bus, authorized_by, reason, *, correlation_id="maintenance",
                               now_millis=None) -> int:
    """Remove every expired, non-revoked trust grant via a trust_grant_pruned event. Returns the count
    pruned. Requires authorized_by + reason — without the operator authorization it refuses."""
    # require non-blank values — a whitespace-only authorized_by/reason is a vacuous audit record (audit)
    if not (authorized_by or "").strip():
        raise ValueError("prune requires an authorized_by (operator authorization)")
    if not (reason or "").strip():
        raise ValueError("prune requires a reason")
    at = _now(now_millis)
    grants = expired_trust_grants(conn, at_millis=at)
    for grant_row_id, role_name, task_class, granted_at in grants:
        event_bus.emit_sync(
            "trust_grant_pruned",
            msgspec.to_builtins(TrustGrantPruned(
                grant_row_id=grant_row_id, role_name=role_name, task_class=task_class,
                granted_at_millis=granted_at, pruned_by=authorized_by, reason=reason,
                pruned_at_millis=at, correlation_id=correlation_id)),
            correlation_id=correlation_id,
        )
    return len(grants)
