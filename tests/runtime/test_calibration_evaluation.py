"""#H5: calibrated-trust evaluation joins the live Brier to grant/renew/revoke on real telemetry.

compute_brier_for_role + grant/renew/revoke/has_active_trust all existed but were never joined, so
SC-5 was never measured on a real path. evaluate_trust closes that: a well-calibrated role earns a
grant, stays trusted via renewal, and is revoked when calibration degrades past the SC-5 threshold.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.calibration.evaluation import evaluate_developer_trust, evaluate_trust
from devharness.calibration.promotion import has_active_trust
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _bus(conn):
    registry = ProjectionRegistry()
    register_handlers(registry)
    return EventBus(conn, registry)


def _seed(bus, n, predicted, observed, task_class, offset=0):
    for i in range(offset, offset + n):
        bus.emit_sync("write_attempted", {"task_id": f"{task_class}-t", "worktree_path": "/w",
                      "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c",
                      "attempted_at_millis": i, "predicted_success": predicted, "task_class": task_class}, correlation_id="c")
        if observed:
            bus.emit_sync("write_applied", {"task_id": f"{task_class}-t", "worktree_path": "/w",
                          "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c",
                          "applied_at_millis": i, "observed_success": True, "task_class": task_class}, correlation_id="c")


def test_grant_then_renew_then_revoke_on_real_brier():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = _bus(conn)

    # well-calibrated: predict 0.95, succeed -> Brier 0.0025 <= 0.15
    _seed(bus, 6, predicted=0.95, observed=True, task_class="feature")
    grant = evaluate_trust("developer", "feature", conn, bus, min_samples=5, now_millis=lambda: 1000)
    assert grant["action"] == "grant"
    assert has_active_trust("developer", "feature", conn, now_millis=lambda: 1000)

    # still calibrated -> renew (keeps trust, does not double-grant)
    renew = evaluate_trust("developer", "feature", conn, bus, min_samples=5, now_millis=lambda: 2000)
    assert renew["action"] == "renew"

    # calibration degrades: predict 0.1 yet succeed (Brier 0.81) -> overall Brier crosses the threshold
    _seed(bus, 12, predicted=0.1, observed=True, task_class="feature", offset=100)
    revoke = evaluate_trust("developer", "feature", conn, bus, min_samples=5, now_millis=lambda: 3000)
    assert revoke["action"] == "revoke" and revoke["brier"] > 0.15
    assert not has_active_trust("developer", "feature", conn, now_millis=lambda: 3000)


def test_insufficient_samples_does_not_grant():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = _bus(conn)
    _seed(bus, 2, predicted=0.95, observed=True, task_class="feature")
    result = evaluate_trust("developer", "feature", conn, bus, min_samples=5, now_millis=lambda: 1)
    assert result == {"brier": None, "action": "insufficient_samples"}
    assert not has_active_trust("developer", "feature", conn, now_millis=lambda: 1)


def test_evaluate_developer_trust_covers_every_write_class():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = _bus(conn)
    actions = evaluate_developer_trust(conn, bus, now_millis=lambda: 1)
    assert set(actions) == {"new_project_scaffold", "feature", "bugfix", "refactor", "dependency_bump"}
    assert all(a == "insufficient_samples" for a in actions.values())  # no telemetry yet
