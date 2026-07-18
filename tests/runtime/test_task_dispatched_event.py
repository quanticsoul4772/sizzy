"""B2.7: TaskDispatched exists with declared fields; EVENT_TYPES is 27."""

import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_task_dispatched_registered():
    assert "task_dispatched" in ev.EVENT_TYPES
    td = msgspec.convert(
        {"plan_id": "p1", "task_id": "t1", "dispatched_to_role": "developer", "dispatched_by_role": "director",
         "correlation_id": "c", "dispatched_at_millis": 5},
        ev.TaskDispatched,
    )
    assert td.plan_id == "p1" and td.dispatched_to_role == "developer" and td.dispatched_by_role == "director"


def test_event_types_count_at_least_27():
    assert len(ev.EVENT_TYPES) >= 27
