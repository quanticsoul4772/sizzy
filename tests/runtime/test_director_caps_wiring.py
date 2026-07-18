"""B4.7: enforce_caps wired into the director dispatch loop for is_oss tasks."""

import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401
from devharness.artifacts.plan import OssEnvelope, PlannedTask
from devharness.events.bus import EventBus
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles import director as director_mod
from devharness.roles.director import DirectorRole, _caps_poll_interval
from devharness.sandbox import registry as sandbox_registry
from devharness.task_classes.builtin import register_builtin_task_classes


def _reasoning():
    async def query(*, prompt, options):
        class _R:
            total_cost_usd = 0.0
        yield _R()
    return MCPReasoningClient(query_fn=query)


class _FakeDeveloper:
    total_cost_usd = 0.0

    @classmethod
    def spawn(cls, *, conn, correlation_id, event_bus, **kwargs):
        return cls(event_bus)

    def __init__(self, event_bus):
        self.event_bus = event_bus

    async def run(self, planned_task, correlation_id):
        # starts the lifecycle (running); in the OSS cap-abort path the worker is cancelled before this runs
        self.event_bus.emit_sync(
            "task_started",
            {"task_id": planned_task.task_id, "role": "developer", "worktree_path": "/w",
             "correlation_id": correlation_id, "started_at_millis": 1},
            correlation_id=correlation_id,
        )


async def _complete_completed(planned_task, developer, conn, event_bus):
    event_bus.emit_sync(
        "terminal_outcome",
        {"task_id": planned_task.task_id, "outcome": "completed", "detail": "", "reason": "",
         "correlation_id": planned_task.correlation_id, "terminated_at_millis": 9},
        correlation_id=planned_task.correlation_id,
    )


def _setup():
    register_builtin_task_classes()
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    bus.emit_sync("plan_drafted", {"plan_id": "p1", "spec_id": "s", "task_count": 1}, correlation_id="c")
    return conn, bus


def _oss_task():
    return PlannedTask(task_id="t1", task_class="feature", description="d", scope_boundary=["**"], dependencies=[],
                       correlation_id="c", verifier_ref="feature_spec_claim", is_oss=True,
                       oss_envelope=OssEnvelope(upstream_repo="octo/widget", license_spdx="MIT", requester_id="r1", target_branch="main"))


def test_poll_interval_env_override(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_CAPS_POLL_INTERVAL_SECONDS", "0.001")
    assert _caps_poll_interval() == 0.001


def test_wall_clock_cap_aborts_in_flight_oss_task(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: True)  # sandbox gate passes admission
    conn, bus = _setup()
    # stepped clock: calls 1-2 (dispatched, started_at) = 0; call 3 (poll) jumps far past the cap
    calls = {"n": 0}

    def now():
        calls["n"] += 1
        return 0 if calls["n"] <= 2 else 10_000_000  # 10000s elapsed >> 1800s default cap

    director = DirectorRole.spawn(conn=conn, correlation_id="c", reasoning=_reasoning(), event_bus=bus, now_millis=now)
    terminal = asyncio.run(director.dispatch(_oss_task(), _FakeDeveloper, conn, bus, plan_id="p1",
                                             complete_task=_complete_completed, now_millis=now))

    assert terminal.outcome == "aborted" and terminal.reason == "cap_exceeded:oss_wall_clock"
    be = conn.execute("SELECT budget_kind, action_taken, subject_id FROM proj_budget_exceeded").fetchone()
    assert be == ("oss_wall_clock", "abort", "t1")
    # the cap-abort terminal landed; the worker's 'completed' terminal never fired
    outcomes = [r[0] for r in conn.execute("SELECT outcome FROM events e JOIN (SELECT seq FROM events WHERE event_type='terminal_outcome') t ON e.seq=t.seq").fetchall()] if False else None
    row = conn.execute("SELECT json_extract(payload,'$.outcome'), json_extract(payload,'$.reason') FROM events WHERE event_type='terminal_outcome'").fetchall()
    assert row == [("aborted", "cap_exceeded:oss_wall_clock")]


def test_non_oss_task_does_not_poll_caps(monkeypatch):
    conn, bus = _setup()
    task = PlannedTask(task_id="t2", task_class="new_project_scaffold", description="d", scope_boundary=["src/**"],
                       dependencies=[], correlation_id="c", verifier_ref="test_suite")  # is_oss defaults False
    director = DirectorRole.spawn(conn=conn, correlation_id="c", reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 3)
    terminal = asyncio.run(director.dispatch(task, _FakeDeveloper, conn, bus, plan_id="p1", complete_task=_complete_completed))

    assert terminal.outcome == "completed"
    assert conn.execute("SELECT count(*) FROM proj_budget_exceeded").fetchone()[0] == 0  # no caps polling
