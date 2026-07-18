"""B4.5: commit_identity_assigned handler inserts proj_commit_identity; rebuild parity holds."""

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


def _emit(bus, oss_task_id, name, sha):
    bus.emit_sync("commit_identity_assigned", {"oss_task_id": oss_task_id, "upstream_repo": "octo/widget", "identity_name": name, "identity_email": f"{name}@x", "assigned_by": "default", "commit_sha": sha, "assigned_at_millis": 5}, correlation_id="c1")


def test_handler_inserts_row():
    conn, _registry, bus = _setup()
    _emit(bus, "t1", "devharness-oss-bot", "a" * 40)
    row = conn.execute("SELECT oss_task_id, upstream_repo, identity_name, assigned_by, commit_sha FROM proj_commit_identity").fetchone()
    assert row == ("t1", "octo/widget", "devharness-oss-bot", "default", "a" * 40)


def test_rebuild_parity_mixed():
    conn, registry, bus = _setup()
    _emit(bus, "t1", "devharness-oss-bot", "a" * 40)
    _emit(bus, "t2", "widget-bot", "b" * 40)
    assert check_projection_rebuild_parity(conn, registry) is True
