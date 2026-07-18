"""B3.9 acceptance: an adversarial round + a synthetic weakened-gate regression."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.adversarial.probes import PROBES, KnownBadProbe
from devharness.adversarial.runner import run_all_probes, run_probe
from devharness.adversarial.scheduler import AdversarialScheduler
from devharness.events.bus import EventBus
from devharness.gates.base import GateDeny, GateOk
from devharness.gates.registry import GATES, register_gate
from devharness.maintenance.fermata import FermataPacing
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def teardown_function():
    GATES.pop("b39_weak_scope_gate", None)


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_full_round_zero_regressions():
    conn, bus = _setup()
    scheduler = AdversarialScheduler()
    fermata = FermataPacing()
    # rev 0.3.90: one step runs the whole probe set (a full round)
    assert scheduler.step(conn, bus, fermata, now_millis=lambda: 5) is True

    runs = conn.execute("SELECT outcome, count(*) FROM proj_adversarial GROUP BY outcome").fetchall()
    assert dict(runs) == {"expected_deny": len(PROBES)}  # every gate denied its known-bad
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='gate_regression_detected'").fetchone()[0] == 0


def test_run_all_probes_summary_zero_regressions():
    conn, bus = _setup()
    summary = run_all_probes(conn, bus, now_millis=lambda: 5)
    # B4.2 added 3 OSS-gate probes; B4.3 the sandbox probe; #M7 the antibody_screen probe; the non-goals
    # guard the task_pursues_non_goal probe -> 13, still 0 regressions
    assert summary["n_probed"] == len(PROBES) == 13
    assert summary["n_regressions"] == 0
    assert summary["n_expected_deny"] == 13


class _WeakScopeGate:
    name = "b39_weak_scope_gate"

    def check(self, context):
        return GateOk()  # regressed: should have denied the out-of-scope write


def test_weakened_gate_caught_then_restored():
    conn, bus = _setup()
    # the genuine scope gate denies its known-bad
    assert isinstance(GATES["scope_gate"].check({"scope_boundary": ["src/**"], "touched_paths": ["x/leak"], "task_id": "p"}), GateDeny)

    # inject a weakened gate + a probe for it -> regression detected
    register_gate("b39_weak_scope_gate", _WeakScopeGate())
    probe = KnownBadProbe(probe_name="b39_weak_probe", target_gate="b39_weak_scope_gate",
                          context_factory=lambda: {"scope_boundary": ["src/**"], "touched_paths": ["secrets/leak.txt"], "task_id": "p"})
    result = run_probe(probe, conn, bus, now_millis=lambda: 9)
    assert result.outcome == "regression_allow"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='gate_regression_detected'").fetchone()[0] == 1

    # restore: the real scope gate still passes its probe (0 new regressions)
    before = conn.execute("SELECT count(*) FROM events WHERE event_type='gate_regression_detected'").fetchone()[0]
    real = run_probe(PROBES["scope_out_of_bounds"], conn, bus, now_millis=lambda: 10)
    assert real.outcome == "expected_deny"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='gate_regression_detected'").fetchone()[0] == before
