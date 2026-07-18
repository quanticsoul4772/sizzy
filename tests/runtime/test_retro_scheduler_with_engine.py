"""B5.1: the B5.0 scheduler now invokes the engine — retro_run captures the engine's real run shape."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.engine import RetroEngine
from devharness.retro.scheduler import RetroScheduler


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_scheduler_runs_engine_and_records_run_shape():
    conn, bus = _setup()
    # a terminal preceded by a workflow_guard deny -> T0 antibody candidate, no LLM
    bus.emit_sync("gate_fired", {"gate": "workflow_guard", "decision": "deny", "reason": "workflow_modified",
                  "purpose": "p", "fix": "f"}, correlation_id="c")
    bus.emit_sync("terminal_outcome", {"task_id": "t1", "outcome": "rejected", "detail": "",
                  "correlation_id": "c", "terminated_at_millis": 1}, correlation_id="c")

    sched = RetroScheduler(engine=RetroEngine(llm_fn=None))
    assert sched.step(conn, bus, now_millis=lambda: 5) == "t1"

    run = conn.execute("SELECT terminal_kind, llm_invoked, candidates_emitted_count, candidate_kinds, t0_matched_signatures FROM proj_retro_runs").fetchone()
    assert run[0] == "rejected" and run[1] == 0 and run[2] == 1  # one T0 candidate, no LLM
    import json
    assert json.loads(run[3]) == ["antibody_candidate"]
    assert "gate_deny_workflow_modified" in json.loads(run[4])
    # the candidate landed in the queue, pending review (no auto-apply — SC-2)
    assert conn.execute("SELECT count(*) FROM proj_antibody_queue WHERE review_state='pending'").fetchone()[0] == 1


def test_llm_unavailable_does_not_consume_the_terminal():
    # rev 0.3.57: a transport failure must leave the terminal QUEUED — the first live spine run
    # burned all 8 terminals in a store because the failure was swallowed to "analyzed, nothing
    # found" and the (task, kind) dedup never re-offers a consumed pair.
    import pytest
    from devharness.retro.llm_client import LLMUnavailable

    conn, bus = _setup()
    # a clean completed terminal (no T0 match, non-hostile) -> routes to the LLM
    bus.emit_sync("terminal_outcome", {"task_id": "t1", "outcome": "completed", "detail": "",
                  "correlation_id": "c", "terminated_at_millis": 1}, correlation_id="c")

    def down_llm(system_prompt, retro_context, tier):
        raise LLMUnavailable("transport down")

    sched = RetroScheduler(engine=RetroEngine(llm_fn=down_llm))
    with pytest.raises(LLMUnavailable):
        sched.step(conn, bus, now_millis=lambda: 5)

    # NO retro_run recorded, terminal still queued
    assert conn.execute("SELECT count(*) FROM proj_retro_runs").fetchone()[0] == 0
    assert sched._next_unprocessed(conn) is not None

    # and once the LLM is back, the SAME terminal processes normally
    sched_ok = RetroScheduler(engine=RetroEngine(llm_fn=lambda s, c, t: []))
    assert sched_ok.step(conn, bus, now_millis=lambda: 6) == "t1"
    assert conn.execute("SELECT count(*) FROM proj_retro_runs").fetchone()[0] == 1
