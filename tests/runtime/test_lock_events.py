"""B2.0: lock event types exist with declared fields; EVENT_TYPES is 20."""

import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_lock_event_types_registered():
    assert "write_lock_acquired" in ev.EVENT_TYPES
    assert "write_lock_released" in ev.EVENT_TYPES
    acq = msgspec.convert(
        {"lock_token": "t", "holder_role": "developer", "correlation_id": "c", "acquired_at_millis": 1},
        ev.WriteLockAcquired,
    )
    assert acq.lock_token == "t" and acq.acquired_at_millis == 1
    rel = msgspec.convert(
        {"lock_token": "t", "holder_role": "developer", "correlation_id": "c", "released_at_millis": 2},
        ev.WriteLockReleased,
    )
    assert rel.released_at_millis == 2


def test_event_types_count_at_least_20():
    # B2.0 brought the catalog to 20; B2.3 adds task_started. The catalog only grows.
    assert len(ev.EVENT_TYPES) >= 20
