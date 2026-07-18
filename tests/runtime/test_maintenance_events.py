"""B3.6: maintenance events exist with declared fields; EVENT_TYPES is 32."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_maintenance_events_registered():
    assert "maintenance_tick" in ev.EVENT_TYPES and "maintenance_action" in ev.EVENT_TYPES
    t = msgspec.convert({"cycle_kind": "consolidate", "tick_at_millis": 5, "correlation_id": "c"}, ev.MaintenanceTick)
    assert t.cycle_kind == "consolidate"
    a = msgspec.convert({"cycle_kind": "audit", "action_description": "ok", "evidence": {"n": 1}, "correlation_id": "c", "action_at_millis": 6}, ev.MaintenanceAction)
    assert a.action_description == "ok" and a.evidence == {"n": 1}


def test_action_description_non_empty_at_construction():
    ev.MaintenanceAction(cycle_kind="prune", action_description="x", evidence={}, correlation_id="c", action_at_millis=1)
    with pytest.raises(ValueError):
        ev.MaintenanceAction(cycle_kind="prune", action_description="", evidence={}, correlation_id="c", action_at_millis=1)


def test_event_types_count_at_least_32():
    assert len(ev.EVENT_TYPES) >= 32
