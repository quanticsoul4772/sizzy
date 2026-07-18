"""B2.4: rewind_performed updates proj_checkpoints.rewound_at_millis; parity holds."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, registry, EventBus(conn, registry)


def _take_then_rewind(bus):
    bus.emit_sync(
        "checkpoint_taken",
        {"task_id": "t1", "checkpoint_id": "cp1", "ref": "sha", "worktree_path": "/w",
         "git_commit_sha": "sha", "taken_at_millis": 5},
        correlation_id="c",
    )
    bus.emit_sync(
        "rewind_performed",
        {"checkpoint_id": "cp1", "task_id": "t1", "worktree_path": "/w", "git_commit_sha": "sha",
         "correlation_id": "c", "rewound_at_millis": 9},
        correlation_id="c",
    )


def test_rewind_sets_rewound_at_millis():
    conn, _registry, bus = _setup()
    _take_then_rewind(bus)
    assert conn.execute("SELECT rewound_at_millis FROM proj_checkpoints WHERE checkpoint_id='cp1'").fetchone()[0] == 9


def test_rebuild_parity_across_take_and_rewind():
    conn, registry, bus = _setup()
    _take_then_rewind(bus)
    assert check_projection_rebuild_parity(conn, registry) is True
