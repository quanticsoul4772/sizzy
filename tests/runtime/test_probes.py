"""B3.7: every registered gate has at least one probe; register_probe single-write."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.adversarial.probes import PROBES, KnownBadProbe, ProbeRegistrationError, register_probe
from devharness.gates.base import GateOk
from devharness.gates.registry import GATES


def _is_b4_stub(gate) -> bool:
    """A B4.0 OSS-gate stub returns GateOk(reason='not_yet_implemented_in_B4.0') and does not
    enforce yet — it gains a probe when it graduates to a real body (B4.2/B4.3). A gate that
    raises on an empty context is a real enforcing gate (needs context), not a stub."""
    try:
        result = gate.check({})
    except Exception:
        return False
    return isinstance(result, GateOk) and "not_yet_implemented" in getattr(result, "reason", "")


def test_every_enforcing_gate_has_a_probe():
    # the probe-coverage invariant applies to enforcing gates; not-yet-implemented B4.0 stubs are
    # legitimately un-probed (a probe against an allow-everything stub would falsely report regression).
    probed_gates = {p.target_gate for p in PROBES.values()}
    for gate_name, gate in GATES.items():
        if _is_b4_stub(gate):
            continue
        assert gate_name in probed_gates, f"no known-bad probe for enforcing gate {gate_name}"


def test_probes_target_registered_gates():
    for probe in PROBES.values():
        assert probe.target_gate in GATES


def test_register_probe_single_write():
    existing = next(iter(PROBES.values()))
    with pytest.raises(ProbeRegistrationError):
        register_probe(KnownBadProbe(probe_name=existing.probe_name, target_gate="scope_gate", context_factory=lambda: {}))
