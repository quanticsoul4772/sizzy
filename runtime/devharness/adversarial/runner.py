"""Adversarial probe runner (B3.7).

Runs a known-bad probe against its target gate and records the outcome. A gate that still denies
the known-bad passes (expected_deny). A gate that returns GateOk has REGRESSED — it emits both an
adversarial_test_run(regression_allow) and a gate_regression_detected with the unexpected reason.
"""

import time
from dataclasses import dataclass

from devharness.gates.base import GateDeny
from devharness.gates.registry import GATES


@dataclass(frozen=True)
class ProbeResult:
    probe_name: str
    target_gate: str
    outcome: str  # expected_deny | regression_allow
    reason: str


def _now(now_millis):
    return (now_millis or (lambda: int(time.time() * 1000)))()


def run_probe(probe, conn, event_bus, *, correlation_id="adversarial", now_millis=None) -> ProbeResult:
    context = probe.context_factory()
    context.setdefault("conn", conn)
    context.setdefault("correlation_id", correlation_id)
    gate = GATES.get(probe.target_gate)
    at = _now(now_millis)

    if gate is None:
        # an unregistered target gate is itself a regression (the gate vanished)
        outcome, reason = "regression_allow", f"target gate {probe.target_gate} is not registered"
    else:
        result = gate.check(context)
        if isinstance(result, GateDeny):
            outcome, reason = "expected_deny", result.reason
        else:
            outcome, reason = "regression_allow", f"gate {probe.target_gate} returned GateOk for a known-bad probe"

    event_bus.emit_sync(
        "adversarial_test_run",
        {"probe_name": probe.probe_name, "target_gate": probe.target_gate, "outcome": outcome,
         "gate_check_reason": reason, "correlation_id": correlation_id, "run_at_millis": at},
        correlation_id=correlation_id,
    )
    if outcome == "regression_allow":
        event_bus.emit_sync(
            "gate_regression_detected",
            {"probe_name": probe.probe_name, "gate_name": probe.target_gate,
             "unexpected_allow_reason": reason, "correlation_id": correlation_id, "detected_at_millis": at},
            correlation_id=correlation_id,
        )
    return ProbeResult(probe_name=probe.probe_name, target_gate=probe.target_gate, outcome=outcome, reason=reason)


def run_all_probes(conn, event_bus, *, correlation_id="adversarial", now_millis=None) -> dict:
    from devharness.adversarial.probes import PROBES

    results = [run_probe(p, conn, event_bus, correlation_id=correlation_id, now_millis=now_millis) for p in PROBES.values()]
    regressions = [r for r in results if r.outcome == "regression_allow"]
    return {
        "n_probed": len(results),
        "n_expected_deny": len(results) - len(regressions),
        "n_regressions": len(regressions),
        "regressions": [r.probe_name for r in regressions],
    }
