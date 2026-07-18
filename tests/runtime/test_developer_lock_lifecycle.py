"""B2.3: developer holds the lock for the task; a concurrent developer is refused (Inv 1)."""

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import PlannedTask
from devharness.events.bus import EventBus
from devharness.lock.base import LockHeldByAnotherRole, SingleWriterLock
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.developer import DeveloperRole
from devharness.worktree.isolate import Worktree


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _task(task_id="t1", correlation_id="c"):
    return PlannedTask(
        task_id=task_id, task_class="new_project_scaffold", description="d",
        scope_boundary=["src/**"], dependencies=[], correlation_id=correlation_id, verifier_ref="test_suite",
    )


def _noop_query():
    async def query(*, prompt, options):
        if False:
            yield None

    return query


def _no_checkpoint(task_id, worktree_path, correlation_id, event_bus, conn):
    return None


def _dev(conn, bus, tmp_path):
    return DeveloperRole.spawn(
        conn=conn, correlation_id="c", event_bus=bus, base_path=str(tmp_path),
        worktree_factory=lambda task_id, base: Worktree(task_id, str(tmp_path / task_id), str(tmp_path)),
        query_fn=_noop_query(), checkpoint_fn=_no_checkpoint,
    )


def test_lock_held_during_and_released_after(tmp_path):
    conn, bus = _setup()
    holds = {}

    def query_checks():
        async def query(*, prompt, options):
            holds["during"] = conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0]
            if False:
                yield None

        return query

    dev = DeveloperRole.spawn(
        conn=conn, correlation_id="c", event_bus=bus, base_path=str(tmp_path),
        worktree_factory=lambda task_id, base: Worktree(task_id, str(tmp_path / task_id), str(tmp_path)),
        query_fn=query_checks(), checkpoint_fn=_no_checkpoint,
    )
    asyncio.run(dev.run(_task(), "c"))
    assert holds["during"] == 1  # held while the worker ran
    assert conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 0  # released after


def test_concurrent_developer_refused(tmp_path):
    conn, bus = _setup()
    # another writer already holds the lock (state lives in proj_lock, shared via conn)
    SingleWriterLock().acquire("developer", "other", bus, conn)
    dev = _dev(conn, bus, tmp_path)
    with pytest.raises(LockHeldByAnotherRole):
        asyncio.run(dev.run(_task(task_id="t2"), "c"))
    # still exactly one holder; the refused developer never started a task
    assert conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM proj_task_started").fetchone()[0] == 0
