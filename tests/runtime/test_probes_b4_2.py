"""B4.2: every-gate-has-a-probe now covers the three graduated gates; sandbox stays exempt."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.adversarial.probes import PROBES
from devharness.gates.base import GateOk
from devharness.gates.registry import GATES


def _is_stub(gate) -> bool:
    try:
        r = gate.check({})
    except Exception:
        return False
    return isinstance(r, GateOk) and "not_yet_implemented" in getattr(r, "reason", "")


def test_graduated_gates_have_probes():
    probed = {p.target_gate for p in PROBES.values()}
    for name in ("workflow_guard", "secret_guard", "scope_guard"):
        assert name in probed


def test_no_stub_gates_remain_after_b4_3():
    # B4.3 graduated the sandbox stub; no gate is a not-yet-implemented stub any longer
    stubs = [name for name, gate in GATES.items() if _is_stub(gate)]
    assert stubs == []


def test_every_enforcing_gate_has_a_probe():
    probed = {p.target_gate for p in PROBES.values()}
    for name, gate in GATES.items():
        if _is_stub(gate):
            continue
        assert name in probed, f"enforcing gate {name} has no probe"
