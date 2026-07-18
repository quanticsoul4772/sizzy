"""B1.4: Invariant 16 — reasoning-budget exceedance halts with
budget_exceeded(reasoning); below-floor tier emits tier_floor_violation."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.roles.base import BudgetExceeded
from devharness.roles.director import DirectorRole
from devharness.task_classes.base import TaskClassSpec
from devharness.task_classes.registry import clear_task_classes, register_task_class


def _reasoning(usage):
    async def query(*, prompt, options):
        class _R:
            total_cost_usd = 0.0
            result = "ok"
            is_error = False

        r = _R()
        r.usage = usage
        yield r

    return MCPReasoningClient(query_fn=query)


def _insert_signed_spec(conn, artifact_id, correlation_id):
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, '{}', ?, 1, 1)",
        (artifact_id, correlation_id),
    )
    conn.commit()


def setup_function():
    clear_task_classes()


def teardown_function():
    clear_task_classes()


def test_reasoning_budget_exceeded_halts_with_event():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    _insert_signed_spec(conn, "spec-1", "corr-1")
    # huge per-call usage against a tiny budget -> exceed on the first reasoning call
    director = DirectorRole.spawn(
        conn=conn, correlation_id="corr-1", reasoning=_reasoning({"input_tokens": 10_000, "output_tokens": 0}),
        event_bus=bus, reasoning_budget_tokens=100, now_millis=lambda: 1,
    )
    with pytest.raises(BudgetExceeded):
        asyncio.run(director.run("spec-1", "corr-1"))

    row = conn.execute("SELECT payload FROM events WHERE event_type='budget_exceeded'").fetchone()
    assert row is not None
    payload = json.loads(row[0])
    assert payload["budget_kind"] == "reasoning"
    assert payload["role"] == "director"
    assert payload["spent"] > payload["limit"]


def test_tier_floor_violation_emitted_with_requested_vs_required():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    _insert_signed_spec(conn, "spec-1", "corr-1")
    register_task_class(
        TaskClassSpec(name="synthetic", reasoning_budget_tokens=10_000, tier_minimum="T3", dominant_gate_sensitivity="reviewer")
    )
    director = DirectorRole.spawn(
        conn=conn, correlation_id="corr-1", reasoning=_reasoning({"input_tokens": 1, "output_tokens": 1}),
        event_bus=bus, now_millis=lambda: 1,
    )
    # the director requests a tier below the class floor
    tasks = [{"task_class": "synthetic", "description": "x", "scope_boundary": [], "dependencies": [], "requested_tier": "T1"}]
    asyncio.run(director.run("spec-1", "corr-1", tasks=tasks))

    row = conn.execute("SELECT payload FROM events WHERE event_type='tier_floor_violation'").fetchone()
    assert row is not None
    payload = json.loads(row[0])
    assert payload["requested_tier"] == "T1"
    assert payload["required_tier"] == "T3"
    assert payload["task_class"] == "synthetic"
