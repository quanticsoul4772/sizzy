"""Discovery role (issue-discovery, step B): a read-only analysis session surfaces candidate work items
into proj_work_item_queue. The SDK is mocked — the role's final-text parsing + emission is what's tested."""

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.discovery import DiscoveryRole
from devharness.roles.synthesis import parse_work_items


class _Result:
    def __init__(self, text):
        self.total_cost_usd = 0.0
        self.result = text
        self.is_error = False


def _query(text):
    async def q(*, prompt, options):
        yield _Result(text)
    return q


def _db():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


def _bus(conn):
    reg = ProjectionRegistry()
    register_handlers(reg)
    return EventBus(conn, reg)


def _repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "main.py").write_text("print('hi')\n")
    return repo


def test_discovery_emits_candidates_into_queue(tmp_path):
    repo = _repo(tmp_path)
    conn = _db()
    bus = _bus(conn)
    items = json.dumps([
        {"title": "Add --json", "description": "Add a --json output flag to the CLI",
         "rationale": "machine-readable output", "kind": "feature", "scope_hint": ["main.py"]},
        {"title": "Fix pager off-by-one", "description": "Fix the off-by-one in the pager",
         "rationale": "correctness", "kind": "bugfix", "scope_hint": ["pager.py"]},
    ])
    role = DiscoveryRole(event_bus=bus, conn=conn, target_repo=str(repo), correlation_id="disc",
                         query_fn=_query(items), now_millis=lambda: 1)
    ids = asyncio.run(role.run())

    assert ids == ["disc-w0", "disc-w1"]
    rows = conn.execute(
        "SELECT candidate_id, title, kind, target_repo, source FROM proj_work_item_queue ORDER BY work_item_row_id"
    ).fetchall()
    assert rows == [
        ("disc-w0", "Add --json", "feature", str(repo), "llm"),
        ("disc-w1", "Fix pager off-by-one", "bugfix", str(repo), "llm"),
    ]


def test_discovery_malformed_output_emits_nothing(tmp_path):
    repo = _repo(tmp_path)
    conn = _db()
    bus = _bus(conn)
    role = DiscoveryRole(event_bus=bus, conn=conn, target_repo=str(repo), correlation_id="disc",
                         query_fn=_query("sorry, no JSON here"), now_millis=lambda: 1)
    assert asyncio.run(role.run()) == []
    assert conn.execute("SELECT count(*) FROM proj_work_item_queue").fetchone()[0] == 0


def test_discovery_caps_at_max(tmp_path):
    repo = _repo(tmp_path)
    conn = _db()
    bus = _bus(conn)
    items = json.dumps([{"title": f"t{i}", "description": f"d{i}", "kind": "feature", "scope_hint": []}
                        for i in range(5)])
    role = DiscoveryRole(event_bus=bus, conn=conn, target_repo=str(repo), correlation_id="d",
                         query_fn=_query(items), now_millis=lambda: 1, max_candidates=2)
    assert asyncio.run(role.run()) == ["d-w0", "d-w1"]


def test_parse_work_items_rejects_bad_kind():
    assert parse_work_items('[{"title":"t","description":"d","kind":"nonsense","scope_hint":[]}]') is None


def test_parse_work_items_accepts_object_wrapper():
    out = parse_work_items('{"work_items":[{"title":"t","description":"d","kind":"refactor","scope_hint":["a/**"]}]}')
    assert out == [{"title": "t", "description": "d", "rationale": "", "kind": "refactor", "scope_hint": ["a/**"]}]
