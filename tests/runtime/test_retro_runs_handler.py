"""B5.0: retro_run handler inserts proj_retro_runs; rebuild parity holds across mixed terminal_kinds."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, registry, EventBus(conn, registry)


def _emit(bus, task_id, kind, sigs, llm, count, candidate_kinds):
    bus.emit_sync("retro_run", {"terminal_outcome_correlation_id": "c", "source_task_id": task_id,
                  "terminal_kind": kind, "t0_matched_signatures": sigs, "llm_invoked": llm,
                  "candidates_emitted_count": count, "candidate_kinds": candidate_kinds, "retro_run_at_millis": 5},
                  correlation_id="c")


def test_handler_inserts_row():
    conn, _registry, bus = _setup()
    _emit(bus, "t1", "rejected", ["sig_a"], True, 2, ["antibody_candidate", "gate_change_candidate"])
    row = conn.execute("SELECT source_task_id, terminal_kind, t0_matched_signatures, llm_invoked, candidates_emitted_count, candidate_kinds FROM proj_retro_runs").fetchone()
    assert row[:2] == ("t1", "rejected")
    assert json.loads(row[2]) == ["sig_a"] and row[3] == 1 and row[4] == 2
    assert json.loads(row[5]) == ["antibody_candidate", "gate_change_candidate"]


def test_rebuild_parity_mixed():
    conn, registry, bus = _setup()
    _emit(bus, "t1", "completed", [], False, 0, [])
    _emit(bus, "t2", "rejected", ["sig_b"], True, 1, ["gate_change_candidate"])
    _emit(bus, "t3", "aborted", [], False, 0, [])
    assert check_projection_rebuild_parity(conn, registry) is True
