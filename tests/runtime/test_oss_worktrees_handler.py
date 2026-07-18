"""B4.4: oss_worktree_created handler inserts proj_oss_worktrees; rebuild parity holds."""

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


def _emit(bus):
    bus.emit_sync("oss_worktree_created", {"oss_task_id": "t1", "upstream_repo": "octo/widget", "target_branch": "main", "fork_branch": "devharness-oss/t1", "worktree_path": "/wt/t1", "created_at_millis": 5}, correlation_id="c1")


def test_handler_inserts_row():
    conn, _registry, bus = _setup()
    _emit(bus)
    row = conn.execute("SELECT oss_task_id, upstream_repo, target_branch, fork_branch, worktree_path, correlation_id, created_at_millis FROM proj_oss_worktrees").fetchone()
    assert row == ("t1", "octo/widget", "main", "devharness-oss/t1", "/wt/t1", "c1", 5)


def test_rebuild_parity():
    conn, registry, bus = _setup()
    _emit(bus)
    # the scope-derived event is event-log-only (no projection) — it must not break rebuild parity
    bus.emit_sync("oss_scope_boundary_derived", {"oss_task_id": "t1", "allowed_paths": ["src/**"], "derivation_basis": "build_class + within_worktree", "derived_at_millis": 6}, correlation_id="c1")
    assert check_projection_rebuild_parity(conn, registry) is True
