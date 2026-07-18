"""Operator-initiated requester revocation (B4.6, §S5).

revoke_requester puts a requester in an effectively-permanent cooldown (so the B4.1 intake cooldown
check refuses them indefinitely) and emits budget_exceeded(requester_revoked, revoke). API-level for
B4.6 — a CLI surface can follow in a later sub-phase if the operator workflow needs it.
"""

import time

import msgspec

from devharness.events.registry import BudgetExceeded

_PERMANENT_MILLIS = 100 * 365 * 24 * 60 * 60 * 1000  # ~100 years


def _now(now_millis_fn):
    return (now_millis_fn or (lambda: int(time.time() * 1000)))()


def revoke_requester(requester_id: str, reason: str, revoked_by: str, conn, event_bus,
                     correlation_id: str, now_millis_fn=None) -> None:
    """Revoke a requester: an effectively-permanent cooldown row + budget_exceeded(requester_revoked)."""
    now = _now(now_millis_fn)
    conn.execute(
        "INSERT INTO proj_requester_cooldown (requester_id, cooldown_until_millis, triggered_by, "
        "trigger_reason, correlation_id, triggered_at_millis) VALUES (?, ?, 'revocation', ?, ?, ?)",
        (requester_id, now + _PERMANENT_MILLIS, f"{reason} (by {revoked_by})", correlation_id, now),
    )
    conn.commit()
    event_bus.emit_sync(
        "budget_exceeded",
        msgspec.to_builtins(BudgetExceeded(
            budget_kind="requester_revoked", action_taken="revoke", subject_id=requester_id,
            reason=reason, exceeded_at_millis=now, correlation_id=correlation_id,
        )),
        correlation_id=correlation_id,
    )
