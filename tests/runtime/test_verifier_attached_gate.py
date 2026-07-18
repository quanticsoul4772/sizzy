"""B2.1: VerifierAttachedGate allows when verifier_ref present, denies when None."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers the falsifiers used below)
from devharness.artifacts.plan import PlannedTask
from devharness.gates.base import GateDeny, GateOk
from devharness.gates.verifier_attached import VerifierAttachedGate


def _task(verifier_ref):
    return PlannedTask(
        task_id="t1", task_class="new_project_scaffold", description="d", scope_boundary=["src/**"],
        dependencies=[], correlation_id="c", verifier_ref=verifier_ref,
    )


def test_allows_when_verifier_present():
    # B2.2 semantic: the verifier_ref must name a registered falsifier
    assert isinstance(VerifierAttachedGate().check({"planned_task": _task("test_suite")}), GateOk)


def test_denies_when_verifier_absent():
    deny = VerifierAttachedGate().check({"planned_task": _task(None)})
    assert isinstance(deny, GateDeny)
    assert deny.reason == "Task verifier_ref is None"
    assert "verification plan" in deny.purpose
    assert deny.fix


def test_denies_when_no_planned_task():
    # the synthetic boot-check context (no planned_task) denies structurally
    deny = VerifierAttachedGate().check({"task_id": "tX"})
    assert isinstance(deny, GateDeny)
