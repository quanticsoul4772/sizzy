"""B3.6: each maintenance cycle runs, emits tick + action with its cycle_kind."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.maintenance.base import AuditCycle, ConsolidateCycle, PruneCycle, SynthesizeCycle
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _rows(conn, kind):
    return conn.execute("SELECT event_kind FROM proj_maintenance WHERE cycle_kind=? ORDER BY maintenance_row_id", (kind,)).fetchall()


def test_each_cycle_emits_tick_and_action():
    for cycle in (ConsolidateCycle(), PruneCycle(), AuditCycle(), SynthesizeCycle()):
        conn, bus = _setup()
        cycle.run(conn, bus, correlation_id="m", now_millis=lambda: 5)
        kinds = [r[0] for r in _rows(conn, cycle.cycle_kind)]
        assert kinds[0] == "tick"
        assert "action" in kinds  # at least one action


def test_audit_reports_chain_valid():
    conn, bus = _setup()
    AuditCycle().run(conn, bus, correlation_id="m", now_millis=lambda: 5)
    import json
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='maintenance_action'").fetchone()[0])
    assert payload["evidence"]["chain_valid"] is True


def test_bounded_work_respected():
    conn, bus = _setup()
    # seed many terminal plans; the consolidate cycle caps at max_events
    for i in range(10):
        conn.execute("INSERT INTO proj_plan (correlation_id, plan_id, spec_artifact_id, task_count, drafted_at_millis, current_state) VALUES (?, ?, 's', 1, 1, 'completed')", (f"c{i}", f"p{i}"))
    conn.commit()
    import json
    ConsolidateCycle().run(conn, bus, correlation_id="m", now_millis=lambda: 5, max_events=4)
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='maintenance_action'").fetchone()[0])
    assert payload["evidence"]["plan_count"] == 4  # capped at max_events
