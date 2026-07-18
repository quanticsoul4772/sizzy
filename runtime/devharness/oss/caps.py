"""Per-task caps for OSS contributions (B4.6, §S5).

Wall-clock and USD ceilings on an OSS task; exceeding either aborts the task with a summary. The
dispatch loop calls check_caps_during_dispatch periodically; on exceedance the caller emits
budget_exceeded(budget_kind=oss_wall_clock|oss_usd, action_taken=abort) and aborts the task.
"""

import os
import time

import msgspec

from devharness.events.registry import BudgetExceeded

DEFAULT_WALL_CLOCK_SECONDS = 1800  # 30 min
DEFAULT_MAX_USD_COST = 5.0


class CapConfig(msgspec.Struct, frozen=True, kw_only=True):
    wall_clock_seconds: float = DEFAULT_WALL_CLOCK_SECONDS
    max_usd_cost: float = DEFAULT_MAX_USD_COST

    @staticmethod
    def from_env() -> "CapConfig":
        wc = os.environ.get("DEVHARNESS_OSS_CAP_WALL_CLOCK_SECONDS")
        usd = os.environ.get("DEVHARNESS_OSS_CAP_USD")
        return CapConfig(
            wall_clock_seconds=float(wc) if wc else DEFAULT_WALL_CLOCK_SECONDS,
            max_usd_cost=float(usd) if usd else DEFAULT_MAX_USD_COST,
        )


class CapResult(msgspec.Struct, frozen=True, kw_only=True):
    exceeded: bool
    kind: str = ""  # oss_wall_clock | oss_usd
    observed: float = 0.0
    limit: float = 0.0


def _now(now_millis_fn):
    return (now_millis_fn or (lambda: int(time.time() * 1000)))()


def check_caps_during_dispatch(task_id: str, started_at_millis: int, accumulated_cost_usd: float,
                               cap_config: CapConfig | None = None, now_millis_fn=None) -> CapResult:
    """Wall-clock first (elapsed since started_at_millis), then USD. The first cap exceeded, or
    exceeded=False under both. The dispatch loop samples this periodically on an is_oss task."""
    cfg = cap_config or CapConfig.from_env()
    elapsed_seconds = (_now(now_millis_fn) - started_at_millis) / 1000
    if elapsed_seconds > cfg.wall_clock_seconds:
        return CapResult(exceeded=True, kind="oss_wall_clock", observed=elapsed_seconds, limit=cfg.wall_clock_seconds)
    if accumulated_cost_usd > cfg.max_usd_cost:
        return CapResult(exceeded=True, kind="oss_usd", observed=accumulated_cost_usd, limit=cfg.max_usd_cost)
    return CapResult(exceeded=False)


def enforce_caps(task_id, started_at_millis, accumulated_cost_usd, event_bus, correlation_id,
                 cap_config: CapConfig | None = None, now_millis_fn=None) -> CapResult:
    """Check caps; on exceedance emit budget_exceeded(kind, action_taken=abort, subject_id=task_id).

    The dispatch loop calls this on an is_oss task; an exceeded result tells it to abort the task with
    terminal_outcome(aborted, reason="cap_exceeded:<kind>"). Returns the CapResult.
    """
    result = check_caps_during_dispatch(task_id, started_at_millis, accumulated_cost_usd, cap_config, now_millis_fn)
    if result.exceeded:
        event_bus.emit_sync(
            "budget_exceeded",
            msgspec.to_builtins(BudgetExceeded(
                budget_kind=result.kind, action_taken="abort", subject_id=task_id,
                limit_value=result.limit, observed_value=result.observed,
                exceeded_at_millis=_now(now_millis_fn), correlation_id=correlation_id,
            )),
            correlation_id=correlation_id,
        )
    return result
