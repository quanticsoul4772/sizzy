"""B4.0: the oss_task_intake handler inserts proj_oss_intake; rebuild parity holds."""

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
    bus.emit_sync("oss_task_intake", {"upstream_repo": "octo/widget", "license_spdx": "Apache-2.0", "requester_id": "r1", "target_branch": "dev", "intake_at_millis": 7}, correlation_id="oss-c")


def test_handler_inserts_row():
    conn, _registry, bus = _setup()
    _emit(bus)
    row = conn.execute("SELECT upstream_repo, license_spdx, requester_id, target_branch, correlation_id, intake_at_millis FROM proj_oss_intake").fetchone()
    assert row == ("octo/widget", "Apache-2.0", "r1", "dev", "oss-c", 7)


def test_rebuild_parity():
    conn, registry, bus = _setup()
    _emit(bus)
    bus.emit_sync("oss_task_intake", {"upstream_repo": "octo/other", "license_spdx": "MIT", "requester_id": "r2", "target_branch": "main", "intake_at_millis": 8}, correlation_id="oss-c2")
    assert check_projection_rebuild_parity(conn, registry) is True
