"""B2.3: TaskStarted exists with declared fields; EVENT_TYPES is 21."""

import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_task_started_registered():
    assert "task_started" in ev.EVENT_TYPES
    ts = msgspec.convert(
        {"task_id": "t1", "role": "developer", "worktree_path": "/w", "correlation_id": "c", "started_at_millis": 7},
        ev.TaskStarted,
    )
    assert ts.task_id == "t1" and ts.role == "developer" and ts.worktree_path == "/w" and ts.started_at_millis == 7


def test_event_types_count_at_least_21():
    # B2.3 brought the catalog to 21; B2.4 adds write_attempted/write_applied/rewind_performed.
    assert len(ev.EVENT_TYPES) >= 21
