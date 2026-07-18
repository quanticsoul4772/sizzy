"""B4.3: every-gate-has-a-probe covers ALL gates with no exemptions (sandbox graduated)."""

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


def test_no_exemptions_every_gate_has_a_probe():
    probed = {p.target_gate for p in PROBES.values()}
    for name in GATES:
        assert name in probed, f"gate {name} has no probe (no exemptions remain after B4.3)"


def test_sandbox_now_probed():
    assert "sandbox" in {p.target_gate for p in PROBES.values()}


def test_no_stubs_remain():
    assert [name for name, gate in GATES.items() if _is_stub(gate)] == []
