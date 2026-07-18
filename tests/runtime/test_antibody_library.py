"""B5.2: antibody library — add/list/revoke/match (text only)."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.antibody_library import add_antibody, list_active_antibodies, match_against_text, revoke_antibody


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_add_emits_and_inserts():
    conn, bus = _setup()
    rid = add_antibody("ignore previous instructions", "cand-1", "operator", conn, bus, now_millis=lambda: 5)
    assert rid == 1
    row = conn.execute("SELECT pattern_text, source_candidate_id, added_by FROM proj_antibody_library WHERE antibody_row_id=1").fetchone()
    assert row == ("ignore previous instructions", "cand-1", "operator")
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='antibody_added'").fetchone()[0] == 1


def test_list_active_and_match():
    conn, bus = _setup()
    add_antibody("leak the secrets", "c1", "op", conn, bus, now_millis=lambda: 1)
    add_antibody("rm -rf /", "c2", "op", conn, bus, now_millis=lambda: 2)
    active = list_active_antibodies(conn)
    assert {a.pattern_text for a in active} == {"leak the secrets", "rm -rf /"}
    assert match_against_text("please leak the secrets now", conn) == ["leak the secrets"]
    assert match_against_text("a clean description", conn) == []


def test_revoke_stops_matching():
    conn, bus = _setup()
    rid = add_antibody("leak the secrets", "c1", "op", conn, bus, now_millis=lambda: 1)
    revoke_antibody(rid, "false positive", "operator", conn, bus, now_millis=lambda: 9)
    assert list_active_antibodies(conn) == []  # revoked -> not active
    assert match_against_text("leak the secrets", conn) == []  # revoked -> no match
    r = conn.execute("SELECT revoked_at_millis, revoke_reason FROM proj_antibody_library WHERE antibody_row_id=?", (rid,)).fetchone()
    assert r == (9, "false positive")
