"""B1.4: TierFloorViolation exists with the declared fields; EVENT_TYPES is 18."""

import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_tier_floor_violation_registered_with_fields():
    assert "tier_floor_violation" in ev.EVENT_TYPES
    tfv = msgspec.convert(
        {
            "role": "director",
            "task_class": "feature",
            "requested_tier": "T1",
            "required_tier": "T2",
            "correlation_id": "c",
            "violated_at_millis": 7,
        },
        ev.TierFloorViolation,
    )
    assert tfv.requested_tier == "T1"
    assert tfv.required_tier == "T2"
    assert tfv.task_class == "feature"


def test_event_types_count_at_least_18():
    # B1.4 brought the catalog to 18; B2.0 adds the two lock events. The catalog only grows.
    assert len(ev.EVENT_TYPES) >= 18
