"""Structured synthesis (spec rev 0.3.23): research composes the spec body (#2a) and the director
decomposes the signed spec into tasks (#2b), each falling back safely to the prior templated /
single-task behaviour on malformed model output."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import msgspec

from devharness.artifacts.spec import Assumption, SpecArtifact
from devharness.events.bus import EventBus
from devharness.mcp.base import CallResult
from devharness.migrate import migrate
from devharness.roles.director import DirectorRole
from devharness.roles.research import ResearchRole
from devharness.roles.synthesis import parse_spec_body, parse_task_list


class _Client:
    """A minimal MCP client whose free-form complete() returns a fixed text."""

    def __init__(self, text):
        self._text = text

    async def complete(self, prompt):
        return CallResult(output=self._text, cost_usd=0.0, usage={}, is_error=False)


# --- unit: parsers ---

def test_parse_spec_body_valid():
    body = parse_spec_body('{"scope":"S","non_goals":["n"],"interfaces":["i"],"success_criteria":["c"],"verification_plan":"V"}')
    assert body == {"scope": "S", "verification_plan": "V", "non_goals": ["n"], "interfaces": ["i"], "success_criteria": ["c"]}


def test_parse_spec_body_rejects_empty_success_criteria():
    assert parse_spec_body('{"scope":"S","non_goals":[],"interfaces":[],"success_criteria":[],"verification_plan":"V"}') is None


def test_parse_spec_body_rejects_nonjson():
    assert parse_spec_body("ok, here is the plan") is None


def test_parse_task_list_valid_with_code_fences():
    tasks = parse_task_list('```json\n[{"task_class":"new_project_scaffold","description":"d","scope_boundary":["a/**"],"dependencies":[]}]\n```')
    assert tasks == [{"task_class": "new_project_scaffold", "description": "d", "scope_boundary": ["a/**"], "dependencies": []}]


def test_parse_task_list_rejects_unknown_class():
    assert parse_task_list('[{"task_class":"nope","description":"d","scope_boundary":[],"dependencies":[]}]') is None


def test_parse_task_list_rejects_nonjson():
    assert parse_task_list("sure, I'll scaffold it") is None


# --- integration: research synthesizes the spec body (#2a) ---

async def _synth_and_persist(role, idea):
    body = await role._synthesize_body(idea)
    return role._draft_and_persist(idea, "c", "c", body=body)


def _research(conn, client):
    r = ResearchRole(parallax=client, event_bus=EventBus(conn), conn=conn, context={})
    r._assumptions = [Assumption(text="single operator", confidence=0.6, low_confidence_flag=True)]
    return r


def test_research_uses_synthesized_body():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    body_json = ('{"scope":"a stdlib CLI","non_goals":["no GUI"],"interfaces":["python -m x"],'
                 '"success_criteria":["tests pass","exit non-zero on violation"],"verification_plan":"pytest"}')
    aid = asyncio.run(_synth_and_persist(_research(conn, _Client(body_json)), "build a CLI"))
    spec = json.loads(conn.execute("SELECT payload_json FROM artifacts WHERE artifact_id=?", (aid,)).fetchone()[0])
    assert spec["scope"] == "a stdlib CLI"
    assert spec["non_goals"] == ["no GUI"]
    assert spec["success_criteria"] == ["tests pass", "exit non-zero on violation"]


def test_research_falls_back_to_template_on_nonjson():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    aid = asyncio.run(_synth_and_persist(_research(conn, _Client("here you go")), "build a CLI"))
    spec = json.loads(conn.execute("SELECT payload_json FROM artifacts WHERE artifact_id=?", (aid,)).fetchone()[0])
    assert spec["scope"].startswith("research-derived scope")  # templated fallback


def test_decompose_prompt_folds_inherent_error_cases_without_dropping_the_split_rule():
    """rev 0.3.64: the decompose prompt carries BOTH directions — the per-behaviour split rule
    (the jqlite under-decomposition fix) AND the inherent-error folding exception (the csvlite
    t2/t5 redundant-task fix: an error case another task's code necessarily produces is folded
    into that task, not planned as an empty-diff standalone), with the own-new-code carve-out
    (a prior drive's exception→exit-code mapping was real work; folding must not swallow it)."""
    from devharness.roles.synthesis import decompose_prompt

    prompt = decompose_prompt({"problem": "p", "scope": "s", "success_criteria": ["c"],
                               "non_goals": [], "assumptions": []})
    # the split rule survives (do not regress to under-decomposition)
    assert "Do not bundle many independently-verifiable behaviours" in prompt
    # the folding exception exists
    assert "inherent error/edge cases" in prompt
    assert "fold it into the description and verification of the task that introduces that code" in prompt
    # the carve-out: real error-handling code still gets its own task
    assert "ONLY when it requires its own new code" in prompt


# --- integration: director decomposes the signed spec (#2b) ---

def _insert_spec(conn, aid, cid):
    spec = SpecArtifact(problem="build a CLI", scope="greenfield", non_goals=[], interfaces=[],
                        success_criteria=["x"], verification_plan="v", assumptions=[], correlation_id=cid)
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, "
        "created_at_millis, signed) VALUES (?, 'spec', 1, ?, ?, 1, 1)",
        (aid, json.dumps(msgspec.to_builtins(spec)), cid),
    )
    conn.commit()


def test_director_uses_decomposed_tasks():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    _insert_spec(conn, "s1", "c")
    tasks_json = '[{"task_class":"new_project_scaffold","description":"scaffold it","scope_boundary":["pkg/**"],"dependencies":[]}]'
    d = DirectorRole.spawn(conn=conn, correlation_id="c", reasoning=_Client(tasks_json), event_bus=EventBus(conn))
    tasks = asyncio.run(d._decompose_spec("s1"))
    assert tasks == [{"task_class": "new_project_scaffold", "description": "scaffold it", "scope_boundary": ["pkg/**"], "dependencies": []}]


def test_director_decompose_falls_back_on_nonjson():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    _insert_spec(conn, "s1", "c")
    d = DirectorRole.spawn(conn=conn, correlation_id="c", reasoning=_Client("ok"), event_bus=EventBus(conn))
    assert asyncio.run(d._decompose_spec("s1")) is None


# --- #M8: an errored CallResult is ignored even when its output would parse ---

class _ErrClient:
    """complete() returns valid-looking output but flags is_error — the output must NOT be used."""

    def __init__(self, text):
        self._text = text

    async def complete(self, prompt):
        return CallResult(output=self._text, cost_usd=0.0, usage={}, is_error=True)


def test_director_decompose_ignores_errored_result():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    _insert_spec(conn, "s1", "c")
    valid = '[{"task_class":"new_project_scaffold","description":"d","scope_boundary":["pkg/**"],"dependencies":[]}]'
    d = DirectorRole.spawn(conn=conn, correlation_id="c", reasoning=_ErrClient(valid), event_bus=EventBus(conn))
    assert asyncio.run(d._decompose_spec("s1")) is None  # is_error -> ignore output, fall back to default


# --- the director resolves dependency references to task_ids ---
# #2b decomposition names deps by task DESCRIPTION (the model has no task_ids yet), but
# PlannedTask.dependencies + _topological_order key on task_id. Unresolved, every edge is silently
# dropped at the topo sort and ordering falls back to list order, masking a broken dependency graph.

class _FullClient:
    """complete() returns a fixed decomposition; the reason tools return benign results so run() completes."""

    def __init__(self, tasks_json):
        self._tasks_json = tasks_json

    async def complete(self, prompt):
        return CallResult(output=self._tasks_json, cost_usd=0.0, usage={}, is_error=False)

    async def reasoning_decision(self, **params):
        return CallResult(output="ok", cost_usd=0.0, usage={}, is_error=False)

    async def reasoning_reflection(self, **params):
        return CallResult(output="ok", cost_usd=0.0, usage={}, is_error=False)


def test_director_resolves_description_dependencies_to_task_ids():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    _insert_spec(conn, "s1", "c")
    # t1 depends on t0 BY DESCRIPTION; t2 names two descriptions plus an unknown ref.
    tasks_json = json.dumps([
        {"task_class": "new_project_scaffold", "description": "scaffold", "scope_boundary": ["pkg/**"], "dependencies": []},
        {"task_class": "feature", "description": "add X", "scope_boundary": ["pkg/x.py"], "dependencies": ["scaffold"]},
        {"task_class": "feature", "description": "add Y", "scope_boundary": ["pkg/y.py"], "dependencies": ["add X", "nonexistent task"]},
    ])
    d = DirectorRole.spawn(conn=conn, correlation_id="c", reasoning=_FullClient(tasks_json), event_bus=EventBus(conn))
    plan_id = asyncio.run(d.run("s1", "c"))
    plan = json.loads(conn.execute("SELECT payload_json FROM artifacts WHERE artifact_id=?", (plan_id,)).fetchone()[0])
    by_id = {t["task_id"]: t for t in plan["tasks"]}
    # the description dep "scaffold" resolves to the scaffold task's id, not the raw string
    assert by_id["c-t1"]["dependencies"] == ["c-t0"]
    # multiple description deps resolve; an unknown ref is dropped (not left to break the topo sort)
    assert by_id["c-t2"]["dependencies"] == ["c-t1"]


def test_research_ignores_errored_result():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    valid = '{"scope":"x","non_goals":[],"interfaces":[],"success_criteria":["c"],"verification_plan":"v"}'
    aid = asyncio.run(_synth_and_persist(_research(conn, _ErrClient(valid)), "build a CLI"))
    spec = json.loads(conn.execute("SELECT payload_json FROM artifacts WHERE artifact_id=?", (aid,)).fetchone()[0])
    assert spec["scope"].startswith("research-derived scope")  # is_error -> templated fallback, not the output
