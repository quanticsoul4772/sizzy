"""Requester cooldowns for OSS intake (B4.6, §S5).

A per-requester rate limit: too many intakes within a window trips a cooldown that refuses further
intakes until it expires. proj_requester_cooldown is DIRECT-WRITTEN runtime state (not an event
projection) — it is excluded from the Invariant-8 parity rebuild; the budget_exceeded event carries
the audit trail of each cooldown trigger.
"""

import os
import time

import msgspec

from devharness.events.registry import BudgetExceeded


class CooldownConfig(msgspec.Struct, frozen=True, kw_only=True):
    max_intakes_per_window: int = 3
    window_seconds: int = 3600
    cooldown_duration_seconds: int = 1800

    @staticmethod
    def from_env() -> "CooldownConfig":
        def _int(name, default):
            v = os.environ.get(name)
            return int(v) if v else default
        return CooldownConfig(
            max_intakes_per_window=_int("DEVHARNESS_OSS_COOLDOWN_MAX_INTAKES", 3),
            window_seconds=_int("DEVHARNESS_OSS_COOLDOWN_WINDOW_SECONDS", 3600),
            cooldown_duration_seconds=_int("DEVHARNESS_OSS_COOLDOWN_DURATION_SECONDS", 1800),
        )


class RateResult(msgspec.Struct, frozen=True, kw_only=True):
    triggered_cooldown: bool
    count: int


class CooldownResult(msgspec.Struct, frozen=True, kw_only=True):
    active: bool
    cooldown_until_millis: int = 0  # the most-future cooldown when active; 0 when inactive


def _now(now_millis_fn):
    return (now_millis_fn or (lambda: int(time.time() * 1000)))()


def check_cooldown(requester_id: str, conn, now_millis_fn=None) -> CooldownResult:
    """The requester's active cooldown (the most-future row with cooldown_until_millis > now), if any."""
    now = _now(now_millis_fn)
    row = conn.execute(
        "SELECT max(cooldown_until_millis) FROM proj_requester_cooldown "
        "WHERE requester_id = ? AND cooldown_until_millis > ?",
        (requester_id, now),
    ).fetchone()
    if row and row[0] is not None:
        return CooldownResult(active=True, cooldown_until_millis=row[0])
    return CooldownResult(active=False)


def _emit_cooldown_budget(event_bus, requester_id, correlation_id, at):
    event_bus.emit_sync(
        "budget_exceeded",
        msgspec.to_builtins(BudgetExceeded(
            budget_kind="oss_requester_cooldown", action_taken="refuse", subject_id=requester_id,
            exceeded_at_millis=at, correlation_id=correlation_id,
        )),
        correlation_id=correlation_id,
    )


def emit_cooldown_refusal(event_bus, requester_id, correlation_id, now_millis_fn=None) -> None:
    """Emit the budget_exceeded(oss_requester_cooldown, refuse) audit when an intake is refused."""
    _emit_cooldown_budget(event_bus, requester_id, correlation_id, _now(now_millis_fn))


def check_intake_rate(requester_id: str, conn, cooldown_config: CooldownConfig, event_bus,
                      correlation_id: str, now_millis_fn=None) -> RateResult:
    """Count recent intakes for the requester; trip a cooldown (+ budget_exceeded) when over the limit.

    By design this counts every `oss_task_intake` in the window regardless of whether the dispatched task
    later rejected/aborted: intake rate-limiting throttles SUBMISSIONS (each consumes intake/review
    capacity), so a requester whose work is rejected and re-submitted still accrues — that is the anti-abuse
    intent, not a bug. (Audit-noted; intentional.)"""
    now = _now(now_millis_fn)
    window_start = now - cooldown_config.window_seconds * 1000
    count = conn.execute(
        "SELECT count(*) FROM events WHERE event_type = 'oss_task_intake' "
        "AND json_extract(payload, '$.requester_id') = ? "
        "AND json_extract(payload, '$.intake_at_millis') >= ?",
        (requester_id, window_start),
    ).fetchone()[0]
    if count >= cooldown_config.max_intakes_per_window:
        until = now + cooldown_config.cooldown_duration_seconds * 1000
        conn.execute(
            "INSERT INTO proj_requester_cooldown (requester_id, cooldown_until_millis, triggered_by, "
            "trigger_reason, correlation_id, triggered_at_millis) VALUES (?, ?, 'rate_limit', ?, ?, ?)",
            (requester_id, until, f"rate_limit: {count} intakes in window", correlation_id, now),
        )
        conn.commit()
        _emit_cooldown_budget(event_bus, requester_id, correlation_id, now)
        return RateResult(triggered_cooldown=True, count=count)
    return RateResult(triggered_cooldown=False, count=count)
