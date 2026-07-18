"""Present + pick (issue-discovery, step C): the presenter lists pending candidates; `select` records the
pick as a question_answered carrying the candidate_id (reusing the answer seam), and refuses an unknown id."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cli.work_items import pending_candidates, select_candidate
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.discovery import DiscoveryRole


class _Result:
    def __init__(self, text):
        self.total_cost_usd = 0.0
        self.result = text


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


def _seed_candidates(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "m.py").write_text("x=1\n")
    conn = _db()
    bus = _bus(conn)
    items = json.dumps([
        {"title": "Add --json", "description": "json output", "kind": "feature", "scope_hint": []},
        {"title": "Fix pager", "description": "off-by-one", "kind": "bugfix", "scope_hint": []},
    ])
    role = DiscoveryRole(event_bus=bus, conn=conn, target_repo=str(repo), correlation_id="disc",
                         query_fn=_query(items), now_millis=lambda: 1)
    asyncio.run(role.run())
    return conn, bus


def test_present_then_select(tmp_path):
    conn, bus = _seed_candidates(tmp_path)
    assert {c[0] for c in pending_candidates(conn)} == {"disc-w0", "disc-w1"}

    select_candidate(conn, bus, "disc-w1")
    answered = [json.loads(p) for (p,) in conn.execute("SELECT payload FROM events WHERE event_type='question_answered'")]
    assert answered[-1]["question_id"] == "disc-pick"
    assert answered[-1]["answer_text"] == "disc-w1"

    # the picked candidate drops out of the pending list
    assert {c[0] for c in pending_candidates(conn)} == {"disc-w0"}


def test_select_unknown_refused(tmp_path):
    conn, bus = _seed_candidates(tmp_path)
    with pytest.raises(ValueError):
        select_candidate(conn, bus, "disc-w9")
