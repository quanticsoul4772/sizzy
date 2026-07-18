"""B3.0: proj_review retired — table dropped; verifier_outcome lands only in proj_verifier_outcomes."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.projections.handlers as handlers_mod
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import PROJECTION_TABLES, register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_proj_review_table_dropped():
    conn, _bus = _setup()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "proj_review" not in tables
    assert "proj_verifier_outcomes" in tables


def test_proj_review_not_in_projection_tables():
    assert "proj_review" not in PROJECTION_TABLES
    assert "proj_verifier_outcomes" in PROJECTION_TABLES


def test_verifier_outcome_lands_only_in_canonical_projection():
    conn, bus = _setup()
    bus.emit_sync("verifier_outcome", {"task_id": "t1", "verifier": "test_suite", "passed": True, "detail": "", "evidence": {"n": 9}}, correlation_id="c")
    row = conn.execute("SELECT verifier_name, outcome FROM proj_verifier_outcomes WHERE task_id='t1'").fetchone()
    assert row == ("test_suite", "pass")


def test_no_code_path_references_proj_review():
    # the handler module no longer writes the retired stand-in
    import inspect
    src = inspect.getsource(handlers_mod)
    # distinctive signature of the retired table (proj_reviewer_certs is a different, live table)
    assert "INSERT INTO proj_review " not in src
    assert "proj_review (task_id, reviewer" not in src
