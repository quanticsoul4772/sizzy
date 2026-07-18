"""B2.4: RewindPerformed exists with the declared fields."""

import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_rewind_performed_registered_with_fields():
    assert "rewind_performed" in ev.EVENT_TYPES
    rp = msgspec.convert(
        {"checkpoint_id": "cp1", "task_id": "t1", "worktree_path": "/w", "git_commit_sha": "sha",
         "correlation_id": "c", "rewound_at_millis": 9},
        ev.RewindPerformed,
    )
    assert rp.checkpoint_id == "cp1" and rp.task_id == "t1" and rp.rewound_at_millis == 9
