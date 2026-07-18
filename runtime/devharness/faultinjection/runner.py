"""Loop-fault runner (feature B).

Drives one probe's fault through a hermetic build and judges the outcome with the live invariant
monitor. The oracle is the count of ``invariant_violated`` events in the HERMETIC store:

  - ``handled``    — the harness turned the fault into exactly one clean terminal; the sweep found
    nothing (0 events).
  - ``regression`` — the fault silently orphaned the task or produced a bad terminal; the sweep fired
    an ``invariant_violated`` (≥1 event).

Why COUNT events, not the sweep's return value (the reviewer's MAJOR finding): ``ConsoleDeveloper.
dispatch`` already runs ``run_invariant_sweep`` internally after it integrates (``console/developer.py``,
feature A), and the sweep dedups — so a SECOND sweep here returns ``[]`` for any dispatch that RETURNED,
even one that returned a bad terminal. We still call the sweep first to flush the one case dispatch's
internal sweep cannot reach (dispatch RAISED before its integrate/sweep line, leaving a live orphan),
then read the authoritative count from the store.

The synthetic build lives only in the hermetic in-memory store; the RESULT events (``loop_fault_run``
always, ``fault_handling_regression`` on a regression) go to the LIVE ``event_bus`` — so the operator's
real log carries only the outcome, never the throwaway build's events.
"""

import json
import time
from dataclasses import dataclass, field

from devharness.faultinjection.hermetic import TEST_CMD, FakeParallax, hermetic_build, noop_query, clean_write_hook
from devharness.monitor.sweep import run_invariant_sweep


@dataclass(frozen=True)
class LoopFaultResult:
    name: str
    fault_class: str
    outcome: str  # handled | regression
    violation_count: int
    invariant_numbers: list = field(default_factory=list)
    detail: str = ""


def _now(now_millis):
    return now_millis() if callable(now_millis) else (now_millis if now_millis is not None else int(time.time() * 1000))


def run_loop_fault(probe, event_bus, *, correlation_id="fault-injection", now_millis=None) -> LoopFaultResult:
    """Run one loop-fault probe against a fresh hermetic build; emit the result to ``event_bus``."""
    at = _now(now_millis)
    build = hermetic_build()
    try:
        dev_kwargs = {
            "base_path": str(build.repo),
            "base_ref": "feature-base",
            "query_fn": noop_query(),
            "write_hook": clean_write_hook,
        }
        probe.patch(dev_kwargs)
        developer = build.developer(test_command=probe.test_command or TEST_CMD)
        # A propagating dispatch exception is itself a mishandling — the sweep below catches the orphan
        # it leaves. (A handled fault never propagates: dispatch forces an aborted terminal, rev 0.3.86.)
        try:
            developer.dispatch(
                build.correlation_id,
                parallax=FakeParallax(),
                developer_kwargs=dev_kwargs,
                snapshot=False,
                spec_claim_retries=probe.spec_claim_retries,
            )
        except Exception:  # noqa: BLE001
            pass
        # Flush the crash-orphan case (dispatch raised before its own integrate/sweep line); a dispatch
        # that returned already swept + deduped, so this is a no-op there.
        try:
            run_invariant_sweep(build.conn, build.writer)
        except Exception:  # noqa: BLE001
            pass
        # Oracle: the authoritative count of violations recorded in the hermetic store.
        violations = [
            json.loads(p)
            for (p,) in build.conn.execute(
                "SELECT payload FROM events WHERE event_type = 'invariant_violated'"
            )
        ]
        violation_count = len(violations)
        invariant_numbers = sorted({v.get("invariant_number") for v in violations if v.get("invariant_number") is not None})
        detail = "; ".join(v.get("detail", "") for v in violations)[:500]
    finally:
        build.cleanup()

    outcome = "regression" if violation_count else "handled"
    event_bus.emit_sync(
        "loop_fault_run",
        {"probe_name": probe.name, "fault_class": probe.fault_class, "outcome": outcome,
         "violation_count": violation_count, "correlation_id": correlation_id, "run_at_millis": at},
        correlation_id=correlation_id,
    )
    if outcome == "regression":
        event_bus.emit_sync(
            "fault_handling_regression",
            {"probe_name": probe.name, "fault_class": probe.fault_class,
             "invariant_numbers": invariant_numbers, "detail": detail,
             "correlation_id": correlation_id, "detected_at_millis": at},
            correlation_id=correlation_id,
        )
    return LoopFaultResult(
        name=probe.name, fault_class=probe.fault_class, outcome=outcome,
        violation_count=violation_count, invariant_numbers=invariant_numbers, detail=detail,
    )


def run_all_loop_faults(event_bus, *, correlation_id="fault-injection", now_millis=None) -> dict:
    from devharness.faultinjection.probes import PROBES

    results = [run_loop_fault(p, event_bus, correlation_id=correlation_id, now_millis=now_millis)
               for p in PROBES.values()]
    regressions = [r for r in results if r.outcome == "regression"]
    return {
        "n_probed": len(results),
        "n_handled": len(results) - len(regressions),
        "n_regressions": len(regressions),
        "regressions": [r.name for r in regressions],
    }
