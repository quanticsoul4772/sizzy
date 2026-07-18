"""B4.0: the director refuses to plan an is_oss task with no recorded intake."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401
from devharness.events.bus import EventBus
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.director import DirectorRole
from devharness.task_classes.builtin import register_builtin_task_classes

CID = "corr-oss"
ENV = {"upstream_repo": "octo/widget", "license_spdx": "MIT", "requester_id": "r1", "target_branch": "main"}


class _R:
    total_cost_usd = 0.0
    result = "ok"
    usage = {"input_tokens": 1, "output_tokens": 1}
    is_error = False


def _reasoning():
    async def query(*, prompt, options):
        yield _R()
    return MCPReasoningClient(query_fn=query)


def _setup():
    register_builtin_task_classes()
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    conn.execute("INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) VALUES ('spec-1','spec',1,'{}',?,1,1)", (CID,))
    conn.commit()
    return conn, bus


def _oss_feature_task():
    return [{"task_class": "feature", "description": "add foo() upstream", "scope_boundary": ["src/**"], "dependencies": [],
             "is_oss": True, "oss_envelope": dict(ENV)}]


def test_no_intake_refuses_and_aborts():
    conn, bus = _setup()
    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    result = asyncio.run(director.run("spec-1", CID, tasks=_oss_feature_task()))

    assert result is None  # planning refused
    kinds = [(json.loads(p[0])["decision_kind"], json.loads(p[0])["detail"]) for p in conn.execute("SELECT payload FROM events WHERE event_type='director_decision'")]
    assert ("abort", "oss_intake_required") in kinds
    assert conn.execute("SELECT count(*) FROM artifacts WHERE artifact_type='plan'").fetchone()[0] == 0  # no plan persisted


def test_matching_intake_lets_planning_proceed():
    conn, bus = _setup()
    # record the intake first (handler inserts proj_oss_intake)
    bus.emit_sync("oss_task_intake", {**ENV, "intake_at_millis": 1}, correlation_id=CID)
    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    plan_id = asyncio.run(director.run("spec-1", CID, tasks=_oss_feature_task()))

    assert plan_id is not None  # planning proceeded
    assert conn.execute("SELECT count(*) FROM artifacts WHERE artifact_id=? AND artifact_type='plan'", (plan_id,)).fetchone()[0] == 1
