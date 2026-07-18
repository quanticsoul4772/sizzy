"""Operator console director action: dispatch the director to plan/decompose the signed spec.

The console action issues the SAME operations as the ``run_director`` driver — resolve the
operator-signed spec, spawn the real ``DirectorRole``, run it plan-only (decompose via
mcp-reasoning unless a task list is injected) — and respects the director's write-free tool
boundary. The director's plan_drafted / director_decision events flow through
``EventBus.emit_sync``; the console writes no event store or projection directly.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.call_class import classify
from devharness.console import ConsoleDirector, NoSignedSpec
from devharness.console.app import ConsoleApp
from devharness.mcp.mcp_reasoning import MCPReasoningClient


def _app():
    """A console connected to a fresh in-memory event store (migrated)."""
    return ConsoleApp(db_path=":memory:").connect()


class _R:
    """A stub SDK ResultMessage carrying usage + a result the director reads."""

    def __init__(self, usage):
        self.total_cost_usd = 0.0
        self.result = "ok"
        self.usage = usage
        self.is_error = False


def _reasoning(usage=None):
    """A fake mcp-reasoning client (the SDK ``query`` is injected — no worker spawned)."""
    usage = usage or {"input_tokens": 10, "output_tokens": 5}

    async def query(*, prompt, options):
        yield _R(usage)

    return MCPReasoningClient(query_fn=query)


def _seed_spec(conn, *, spec_id="spec-1", correlation_id="proj-1", signed=1, created_at=100):
    """Insert a spec artifact the way the research role's storage does (signed by default)."""
    body = {"problem": "a stdlib repo-consistency checker", "correlation_id": correlation_id}
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, ?, ?, ?, ?)",
        (spec_id, json.dumps(body), correlation_id, created_at, signed),
    )
    conn.commit()
    return spec_id


_TASKS = [
    {
        "task_class": "new_project_scaffold",
        "description": "scaffold the package",
        "scope_boundary": ["pkg/**", "tests/pkg/**"],
        "dependencies": [],
    }
]


def _events(conn, event_type):
    return [
        json.loads(payload)
        for (payload,) in conn.execute(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY seq", (event_type,)
        )
    ]


def test_director_returns_bound_action():
    app = _app()
    assert isinstance(app.director(), ConsoleDirector)


def test_plan_refuses_when_no_signed_spec():
    app = _app()
    # an UNsigned spec for the correlation is not a signed spec to plan
    _seed_spec(app.conn, signed=0)
    with pytest.raises(NoSignedSpec):
        app.director().plan("proj-1", reasoning=_reasoning())


def test_director_role_has_no_write_tools():
    app = _app()
    director = app.director().spawn_director("proj-1", reasoning=_reasoning())
    assert director.allowed_mcp_servers == ["mcp-reasoning", "parallax"]
    inv = director.tool_inventory
    assert "Edit" not in inv and "Write" not in inv and "Bash" not in inv
    assert all(classify(tool) != "mutation" for tool in inv)


def test_plan_injected_tasks_drafts_a_plan_artifact():
    app = _app()
    _seed_spec(app.conn)

    plan_id = app.director().plan("proj-1", tasks=_TASKS, reasoning=_reasoning())

    assert plan_id is not None
    row = app.conn.execute(
        "SELECT artifact_type FROM artifacts WHERE artifact_id = ?", (plan_id,)
    ).fetchone()
    assert row == ("plan",)
    # the plan carries the injected task; the director never wrote a file
    payload = json.loads(
        app.conn.execute(
            "SELECT payload_json FROM artifacts WHERE artifact_id = ?", (plan_id,)
        ).fetchone()[0]
    )
    assert [t["task_class"] for t in payload["tasks"]] == ["new_project_scaffold"]


def test_plan_announces_plan_drafted_after_a_decision():
    app = _app()
    _seed_spec(app.conn)
    app.director().plan("proj-1", tasks=_TASKS, reasoning=_reasoning())

    order = [row[0] for row in app.conn.execute("SELECT event_type FROM events ORDER BY seq")]
    assert "plan_drafted" in order
    assert order.index("director_decision") < order.index("plan_drafted")
    drafted = _events(app.conn, "plan_drafted")
    assert len(drafted) == 1
    assert drafted[0]["spec_id"] == "spec-1"


def test_plan_decomposes_when_no_tasks_injected():
    app = _app()
    _seed_spec(app.conn)
    # no injected tasks -> the director decomposes the spec via mcp-reasoning (#2b);
    # the stub completion is non-JSON, so it falls back to the single-task default and still drafts.
    plan_id = app.director().plan("proj-1", reasoning=_reasoning())
    assert plan_id is not None
    assert app.conn.execute(
        "SELECT artifact_type FROM artifacts WHERE artifact_id = ?", (plan_id,)
    ).fetchone() == ("plan",)


def test_plan_resolves_the_latest_signed_spec():
    app = _app()
    _seed_spec(app.conn, spec_id="spec-old", created_at=100)
    _seed_spec(app.conn, spec_id="spec-new", created_at=200)

    plan_id = app.director().plan("proj-1", tasks=_TASKS, reasoning=_reasoning())

    drafted = _events(app.conn, "plan_drafted")
    assert drafted[0]["spec_id"] == "spec-new"
    payload = json.loads(
        app.conn.execute(
            "SELECT payload_json FROM artifacts WHERE artifact_id = ?", (plan_id,)
        ).fetchone()[0]
    )
    assert payload["spec_artifact_id"] == "spec-new"


def test_explicit_spec_id_overrides_resolution():
    app = _app()
    _seed_spec(app.conn, spec_id="spec-old", created_at=100)
    _seed_spec(app.conn, spec_id="spec-new", created_at=200)

    app.director().plan("proj-1", spec_id="spec-old", tasks=_TASKS, reasoning=_reasoning())

    assert _events(app.conn, "plan_drafted")[0]["spec_id"] == "spec-old"


def test_plan_refuses_an_unsigned_spec_id():
    app = _app()
    _seed_spec(app.conn, spec_id="spec-unsigned", signed=0)
    # the director refuses to plan an unsigned spec: returns None, drafts no plan, records an abort
    plan_id = app.director().plan("proj-1", spec_id="spec-unsigned", tasks=_TASKS, reasoning=_reasoning())
    assert plan_id is None
    assert _events(app.conn, "plan_drafted") == []
    kinds = [d["decision_kind"] for d in _events(app.conn, "director_decision")]
    assert "abort" in kinds


def test_plan_is_plan_only_no_dispatch():
    app = _app()
    _seed_spec(app.conn)
    app.director().plan("proj-1", tasks=_TASKS, reasoning=_reasoning())
    # plan-only, exactly like run_director: the director drafts but never dispatches a developer
    assert _events(app.conn, "task_dispatched") == []
    assert app.conn.execute("SELECT COUNT(*) FROM proj_task_lifecycle").fetchone()[0] == 0


def test_now_millis_seam_stamps_the_plan():
    app = _app()
    _seed_spec(app.conn)
    director = ConsoleDirector(app.conn, app.writer, now_millis=lambda: 4242)
    plan_id = director.plan("proj-1", tasks=_TASKS, reasoning=_reasoning())
    payload = json.loads(
        app.conn.execute(
            "SELECT payload_json FROM artifacts WHERE artifact_id = ?", (plan_id,)
        ).fetchone()[0]
    )
    assert payload["created_at_millis"] == 4242


def _reasoning_flaky(fail_times, usage=None):
    """A reasoning client whose SDK query raises the transient 'error result: success' the first
    ``fail_times`` calls, then succeeds — to exercise the rev-0.3.86 retry."""
    calls = {"n": 0}

    async def query(*, prompt, options):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise RuntimeError("Claude Code returned an error result: success")
        yield _R(usage)

    return MCPReasoningClient(query_fn=query), calls


def test_plan_retries_the_transient_sdk_error():
    app = _app()
    _seed_spec(app.conn)
    reasoning, calls = _reasoning_flaky(1)
    plan_id = app.director().plan("proj-1", reasoning=reasoning)  # transient once -> retried -> succeeds
    assert plan_id is not None
    assert calls["n"] >= 2  # it got past the transient (a retry happened)


def test_plan_does_not_retry_a_non_transient_error():
    app = _app()
    _seed_spec(app.conn)
    calls = {"n": 0}

    async def query(*, prompt, options):
        calls["n"] += 1
        raise RuntimeError("a genuine failure, not the transient")
        yield  # pragma: no cover

    import pytest
    with pytest.raises(RuntimeError, match="genuine failure"):
        app.director().plan("proj-1", reasoning=MCPReasoningClient(query_fn=query))
    assert calls["n"] == 1  # raised immediately, not retried
