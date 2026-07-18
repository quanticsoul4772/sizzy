"""B3.4: director planning for task_class='refactor' wires verifier_ref."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import msgspec

import devharness.verifier.builtin  # noqa: F401
from devharness.artifacts.plan import PlanArtifact
from devharness.events.bus import EventBus
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.roles.director import DirectorRole
from devharness.task_classes.builtin import register_builtin_task_classes


class _R:
    total_cost_usd = 0.0
    result = "ok"
    usage = {"input_tokens": 1, "output_tokens": 1}
    is_error = False


def _reasoning():
    async def query(*, prompt, options):
        yield _R()
    return MCPReasoningClient(query_fn=query)


def test_refactor_planning_sets_verifier():
    register_builtin_task_classes()
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    conn.execute("INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) VALUES ('spec-1','spec',1,'{}','c',1,1)")
    conn.commit()
    director = DirectorRole.spawn(conn=conn, correlation_id="c", reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    tasks = [{"task_class": "refactor", "description": "extract helper", "scope_boundary": ["src/**"], "dependencies": []}]
    plan_id = asyncio.run(director.run("spec-1", "c", tasks=tasks))

    row = conn.execute("SELECT payload_json FROM artifacts WHERE artifact_id=? AND artifact_type='plan'", (plan_id,)).fetchone()
    task = msgspec.convert(json.loads(row[0]), PlanArtifact).tasks[0]
    assert task.task_class == "refactor"
    assert task.verifier_ref == "refactor_behavior_preserving"
