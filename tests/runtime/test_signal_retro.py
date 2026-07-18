"""§S7 learning-loop closure: invariant_violated / fault_handling_regression → advisory gate-change candidates.

These two signals are unreachable by the terminal-triggered retro path, so SignalRetroScheduler drains them
directly (dedup via proj_signal_retro_runs) and reuses the RetroEngine T0 path to emit a `tighten`,
non-core, advisory gate_change_candidate that stays `pending` for operator review (Inv 12 preserved)."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.base import RetroContext
from devharness.retro.engine import RetroEngine
from devharness.retro.signal_scheduler import SignalRetroScheduler


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _sched():
    return SignalRetroScheduler(engine=RetroEngine(llm_fn=None))


def _emit_invariant_violated(bus, *, cid="build-1", task_id="build-1-t0"):
    bus.emit_sync(
        "invariant_violated",
        {"invariant_number": 10, "property": "exactly-one-terminal-per-task", "dedup_key": "10|t0|",
         "offending_event_ids": [], "task_id": task_id, "correlation_id": cid,
         "detail": "orphaned: task_started with no terminal", "detected_at_millis": 5},
        correlation_id=cid,
    )


def _emit_fault_regression(bus, *, cid="fault-injection"):
    bus.emit_sync(
        "fault_handling_regression",
        {"probe_name": "mid_dispatch_crash", "fault_class": "worker_crash", "invariant_numbers": [10],
         "detail": "orphaned: task_started with no terminal", "correlation_id": cid, "detected_at_millis": 5},
        correlation_id=cid,
    )


def _candidates(conn):
    return conn.execute(
        "SELECT target_gate, change_kind, review_state, source, signature_name FROM proj_gate_change_queue"
    ).fetchall()


def test_invariant_violated_becomes_a_pending_gate_change_candidate():
    conn, bus = _setup()
    _emit_invariant_violated(bus)
    processed = _sched().step(conn, bus, now_millis=lambda: 7)

    assert processed is not None
    rows = _candidates(conn)
    assert len(rows) == 1
    target_gate, change_kind, review_state, source, signature_name = rows[0]
    assert target_gate == "invariant_monitor"
    assert change_kind == "tighten"
    assert review_state == "pending"  # Inv 12: a non-core tighten is never auto-rejected
    assert source == "t0"
    assert signature_name == "monitor_invariant_violated"
    # ledger recorded for this signal event
    assert conn.execute("SELECT COUNT(*) FROM proj_signal_retro_runs").fetchone()[0] == 1
    assert conn.execute("SELECT signal_event_type FROM proj_signal_retro_runs").fetchone()[0] == "invariant_violated"


def test_fault_handling_regression_becomes_a_pending_gate_change_candidate():
    conn, bus = _setup()
    _emit_fault_regression(bus)
    _sched().step(conn, bus, now_millis=lambda: 7)

    rows = _candidates(conn)
    assert len(rows) == 1
    assert rows[0][0] == "fault_handling"  # target_gate
    assert rows[0][1] == "tighten"
    assert rows[0][2] == "pending"
    assert rows[0][4] == "loop_fault_regression"  # signature_name


def test_dedup_a_processed_signal_is_never_re_analyzed():
    conn, bus = _setup()
    _emit_invariant_violated(bus)
    sched = _sched()
    assert sched.step(conn, bus, now_millis=lambda: 7) is not None
    assert sched.step(conn, bus, now_millis=lambda: 8) is None  # already processed
    assert len(_candidates(conn)) == 1  # no duplicate candidate


def test_drains_both_signal_types_in_order():
    conn, bus = _setup()
    _emit_invariant_violated(bus)
    _emit_fault_regression(bus)
    sched = _sched()
    n = 0
    while sched.step(conn, bus, now_millis=lambda: 7) is not None:
        n += 1
    assert n == 2
    assert len(_candidates(conn)) == 2
    assert conn.execute("SELECT COUNT(*) FROM proj_signal_retro_runs").fetchone()[0] == 2


class _HeldFermata:
    def is_held(self, conn):
        return True


def test_scheduler_is_fermata_gated():
    conn, bus = _setup()
    _emit_invariant_violated(bus)
    sched = SignalRetroScheduler(engine=RetroEngine(llm_fn=None), fermata=_HeldFermata())
    assert sched.step(conn, bus, now_millis=lambda: 7) is None
    assert len(_candidates(conn)) == 0


def test_terminal_path_does_not_fire_signal_signatures():
    """#1 guard: an invariant_violated in a TERMINAL context's preceding_events must NOT emit a
    monitor_invariant_violated candidate. The terminal-triggered RetroScheduler shares the engine; without
    the signal-only gate it would double-emit for a re-driven terminal whose preceding set includes an
    earlier invariant_violated (same correlation, lower seq)."""
    conn, bus = _setup()
    ctx = RetroContext(
        terminal_outcome_event={"outcome": "completed", "task_id": "t"},  # populated -> a terminal context
        preceding_events=[{"event_id": "iv-1", "event_type": "invariant_violated", "payload": {"invariant_number": 10}}],
        calibration_snapshot={}, source_task_id="t", correlation_id="X",
    )
    RetroEngine(llm_fn=None).analyze(ctx, bus, now_millis=lambda: 7)
    assert conn.execute(
        "SELECT COUNT(*) FROM proj_gate_change_queue WHERE target_gate = 'invariant_monitor'"
    ).fetchone()[0] == 0


def test_open_candidate_guard_collapses_repeats_until_reviewed():
    """#5/#2 guard: a second same-category signal while the first candidate is pending emits NO new
    candidate (still ledgered); once the first is reviewed (no longer pending), the next signal emits a
    fresh one."""
    conn, bus = _setup()
    sched = _sched()
    _emit_invariant_violated(bus, cid="build-1", task_id="t1")
    sched.step(conn, bus, now_millis=lambda: 7)
    assert len(_candidates(conn)) == 1

    _emit_invariant_violated(bus, cid="build-2", task_id="t2")  # distinct event, same target_gate
    sched.step(conn, bus, now_millis=lambda: 8)
    assert len(_candidates(conn)) == 1  # collapsed — still one open candidate
    assert conn.execute("SELECT COUNT(*) FROM proj_signal_retro_runs").fetchone()[0] == 2  # both ledgered

    conn.execute("UPDATE proj_gate_change_queue SET review_state = 'approved'")  # operator reviews it
    conn.commit()
    _emit_invariant_violated(bus, cid="build-3", task_id="t3")
    sched.step(conn, bus, now_millis=lambda: 9)
    assert len(_candidates(conn)) == 2  # a fresh candidate now that none is pending


def test_populated_signal_retro_runs_rebuilds_identically():
    """#3 Inv-8 parity: proj_signal_retro_runs (+ the candidates it drove) round-trip a from-scratch
    replay — the generic parity test only exercises it empty."""
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    reg = ProjectionRegistry()
    register_handlers(reg)
    bus = EventBus(conn, reg)
    _emit_invariant_violated(bus)
    _emit_fault_regression(bus)
    sched = SignalRetroScheduler(engine=RetroEngine(llm_fn=None))
    while sched.step(conn, bus, now_millis=lambda: 7) is not None:
        pass
    assert conn.execute("SELECT COUNT(*) FROM proj_signal_retro_runs").fetchone()[0] == 2
    assert check_projection_rebuild_parity(conn, reg) is True
