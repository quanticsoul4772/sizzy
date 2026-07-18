"""B4.5: CommitIdentityAssigned event — declared fields; EVENT_TYPES 39."""

import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev

SHA = "a" * 40


def test_commit_identity_assigned_registered():
    assert "commit_identity_assigned" in ev.EVENT_TYPES
    e = msgspec.convert(
        {"oss_task_id": "t1", "upstream_repo": "octo/widget", "identity_name": "devharness-oss-bot",
         "identity_email": "oss@devharness.local", "assigned_by": "default", "commit_sha": SHA,
         "assigned_at_millis": 5, "correlation_id": "c"},
        ev.CommitIdentityAssigned,
    )
    assert e.commit_sha == SHA and e.assigned_by == "default" and len(e.commit_sha) == 40


def test_event_types_count_at_least_39():
    assert len(ev.EVENT_TYPES) >= 39
