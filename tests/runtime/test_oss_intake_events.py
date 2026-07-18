"""B4.0: OssTaskIntake exists with declared fields; EVENT_TYPES is 35."""

import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_oss_task_intake_registered():
    assert "oss_task_intake" in ev.EVENT_TYPES
    i = msgspec.convert(
        {"upstream_repo": "octo/widget", "license_spdx": "MIT", "requester_id": "r1",
         "target_branch": "main", "intake_at_millis": 5, "correlation_id": "c"},
        ev.OssTaskIntake,
    )
    assert i.upstream_repo == "octo/widget" and i.requester_id == "r1" and i.target_branch == "main"


def test_event_types_count_at_least_35():
    assert len(ev.EVENT_TYPES) >= 35
