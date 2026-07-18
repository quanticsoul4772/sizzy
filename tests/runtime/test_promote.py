"""Promote (issue-discovery, step D): the chosen candidate becomes a signed-pending SpecArtifact with no
interview — and the spec is valid enough for the director to load (assumptions non-empty, msgspec-convertible)."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.spec import SpecArtifact
from devharness.cli.work_items import select_candidate
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.discovery import DiscoveryRole
from devharness.roles.promote import chosen_candidate, promote


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


def _seed_and_pick(tmp_path, pick="disc-w0"):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "m.py").write_text("x=1\n")
    conn = _db()
    bus = _bus(conn)
    items = json.dumps([
        {"title": "Add --json", "description": "Add a --json output flag", "kind": "feature", "scope_hint": ["m.py"]},
        {"title": "Fix pager", "description": "off-by-one", "kind": "bugfix", "scope_hint": []},
    ])
    role = DiscoveryRole(event_bus=bus, conn=conn, target_repo=str(repo), correlation_id="disc",
                         query_fn=_query(items), now_millis=lambda: 1)
    asyncio.run(role.run())
    select_candidate(conn, bus, pick)
    return conn, bus


class _Body:
    def __init__(self, output):
        self.output = output
        self.is_error = False


class _Parallax:
    def __init__(self, body_json):
        self.body_json = body_json

    async def complete(self, prompt):
        return _Body(self.body_json)


def test_promote_drafts_signed_pending_spec_no_interview(tmp_path):
    conn, bus = _seed_and_pick(tmp_path, "disc-w0")
    body = json.dumps({"scope": "add the flag", "non_goals": [], "interfaces": ["--json"],
                       "success_criteria": ["--json prints valid JSON"], "verification_plan": "unit tests"})
    spec_id = asyncio.run(promote(conn, bus, "disc", parallax=_Parallax(body), now_millis=lambda: 9))

    row = conn.execute("SELECT artifact_type, signed, payload_json FROM artifacts WHERE artifact_id = ?",
                       (spec_id,)).fetchone()
    assert row[0] == "spec" and row[1] == 0
    # the persisted spec loads under msgspec (assumptions non-empty — the director can read it)
    spec = msgspec.convert(json.loads(row[2]), SpecArtifact)
    assert spec.problem == "Add a --json output flag"
    assert spec.scope == "add the flag"
    assert spec.assumptions and spec.assumptions[0].confidence == 1.0


def test_promote_templated_fallback_when_no_parallax(tmp_path):
    conn, bus = _seed_and_pick(tmp_path, "disc-w1")
    spec_id = asyncio.run(promote(conn, bus, "disc", parallax=None, now_millis=lambda: 9))
    spec = msgspec.convert(
        json.loads(conn.execute("SELECT payload_json FROM artifacts WHERE artifact_id=?", (spec_id,)).fetchone()[0]),
        SpecArtifact)
    assert spec.is_valid()  # complete + non-empty assumptions
    assert "Fix pager" in spec.scope


def test_promote_without_a_pick_raises(tmp_path):
    repo = tmp_path / "p"
    repo.mkdir()
    conn = _db()
    bus = _bus(conn)
    with pytest.raises(ValueError):
        asyncio.run(promote(conn, bus, "disc", parallax=None))


def test_chosen_candidate_reads_the_pick(tmp_path):
    conn, _ = _seed_and_pick(tmp_path, "disc-w1")
    assert chosen_candidate(conn, "disc")["candidate_id"] == "disc-w1"
