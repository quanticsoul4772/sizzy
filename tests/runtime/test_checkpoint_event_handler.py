"""B2.4: checkpoint_taken inserts proj_checkpoints (rewound NULL); parity holds."""

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


def _emit_taken(bus):
    bus.emit_sync(
        "checkpoint_taken",
        {"task_id": "t1", "checkpoint_id": "cp1", "ref": "sha", "worktree_path": "/w",
         "git_commit_sha": "sha", "taken_at_millis": 5},
        correlation_id="c",
    )


def test_inserts_proj_checkpoints_row():
    conn, _registry, bus = _setup()
    _emit_taken(bus)
    row = conn.execute(
        "SELECT task_id, worktree_path, git_commit_sha, taken_at_millis, rewound_at_millis "
        "FROM proj_checkpoints WHERE checkpoint_id='cp1'"
    ).fetchone()
    assert row == ("t1", "/w", "sha", 5, None)


def test_rebuild_parity():
    conn, registry, bus = _setup()
    _emit_taken(bus)
    assert check_projection_rebuild_parity(conn, registry) is True
