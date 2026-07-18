"""B3.7: a weakened gate (allows a known-bad) is caught by its probe; the real gate still passes."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.adversarial.probes import PROBES, KnownBadProbe
from devharness.adversarial.runner import run_probe
from devharness.events.bus import EventBus
from devharness.gates.base import GateOk
from devharness.gates.registry import GATES, register_gate
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def teardown_function():
    GATES.pop("b37_weakened_scope_gate", None)  # don't leak the test gate into the global registry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


class _WeakenedScopeGate:
    """A scope gate that has regressed: it no longer denies out-of-scope writes."""

    name = "b37_weakened_scope_gate"

    def check(self, context):
        return GateOk()  # the regression: should have denied


def test_weakened_gate_is_caught():
    conn, bus = _setup()
    if "b37_weakened_scope_gate" not in GATES:
        register_gate("b37_weakened_scope_gate", _WeakenedScopeGate())
    probe = KnownBadProbe(
        probe_name="b37_weakened_scope_probe", target_gate="b37_weakened_scope_gate",
        context_factory=lambda: {"scope_boundary": ["src/**"], "touched_paths": ["secrets/leak.txt"], "task_id": "p"},
    )
    result = run_probe(probe, conn, bus, now_millis=lambda: 5)
    assert result.outcome == "regression_allow"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='gate_regression_detected'").fetchone()[0] == 1


def test_real_scope_gate_still_passes_its_probe():
    conn, bus = _setup()
    # the genuine scope_gate still denies its known-bad -> no regression
    result = run_probe(PROBES["scope_out_of_bounds"], conn, bus, now_millis=lambda: 5)
    assert result.outcome == "expected_deny"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='gate_regression_detected'").fetchone()[0] == 0
