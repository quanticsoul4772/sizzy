"""B4.2: secret_guard adversarial — known-bad denies; a weakened fixture is caught."""

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

_WEAK_NAME = "b42_weak_secret_guard"


def teardown_function():
    GATES.pop(_WEAK_NAME, None)


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


class _Weak:
    name = _WEAK_NAME

    def check(self, context):
        return GateOk()  # regressed: should have denied


def test_content_known_bad_denies():
    conn, bus = _setup()
    result = run_probe(PROBES["secret_in_diff"], conn, bus, now_millis=lambda: 5)
    assert result.outcome == "expected_deny"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='gate_regression_detected'").fetchone()[0] == 0


def test_path_known_bad_denies():
    # B4.2-reconciliation: the path axis also denies its known-bad (a secret-named file)
    conn, bus = _setup()
    probe = KnownBadProbe(probe_name="secret_named_file", target_gate="secret_guard",
                          context_factory=lambda: {"touched_paths": [".env"]})
    result = run_probe(probe, conn, bus, now_millis=lambda: 5)
    assert result.outcome == "expected_deny"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='gate_regression_detected'").fetchone()[0] == 0


def test_weakened_gate_caught():
    conn, bus = _setup()
    register_gate(_WEAK_NAME, _Weak())
    probe = KnownBadProbe(probe_name="b42_weak_secret_in_diff", target_gate=_WEAK_NAME, context_factory=lambda: {'diff_content': '+t = ghp_' + 'a'*36})
    result = run_probe(probe, conn, bus, now_millis=lambda: 9)
    assert result.outcome == "regression_allow"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='gate_regression_detected'").fetchone()[0] == 1
