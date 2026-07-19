"""#H2: the maintenance/retro/adversarial driver wires + steps the schedulers on a real event log.

drive() builds the three step-driven schedulers (sharing one fermata) and runs a maintenance pass.
Proven here against a seeded log, no live spend: a benign terminal routes to the LLM residue path
(fake llm_fn) and emits a candidate; a gate-deny terminal takes the deterministic T0 path; the
maintenance cycle + adversarial probe run when the fermata is released.
"""

import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime"))
sys.path.insert(0, str(REPO / "scripts"))

from devharness.events.bus import EventBus, verify_chain
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from run_maintenance import drive


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry), registry


def _terminal(bus, task_id, outcome="completed"):
    bus.emit_sync("terminal_outcome", {"task_id": task_id, "outcome": outcome, "detail": "",
                  "correlation_id": "c", "terminated_at_millis": 1}, correlation_id="c")


def test_driver_runs_retro_llm_residue_plus_maintenance_and_adversarial():
    conn, bus, registry = _setup()
    _terminal(bus, "t-clean", "completed")  # benign: no T0 signature -> LLM residue path

    fake_llm = lambda system, ctx, tier: [
        {"kind": "antibody_candidate", "signature_name": "novel_x", "pattern_text": "watch X", "evidence_event_ids": []}
    ]
    summary = drive(conn, bus, llm_fn=fake_llm, idle_millis=24 * 3600 * 1000, now_millis=lambda: 5)

    assert "t-clean" in summary["retro_processed"]
    assert summary["maintenance_cycle"] is not None          # a cycle ran (fermata released, deep idle)
    assert summary["adversarial_probe_ran"] is True          # a probe ran
    # the LLM residue candidate reached the operator-review queue with source=llm
    rows = [r[0] for r in conn.execute("SELECT json_extract(payload,'$.source') FROM events WHERE event_type='antibody_candidate'")]
    assert "llm" in rows
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='retro_run'").fetchone()[0] == 1
    assert verify_chain(conn) == conn.execute("SELECT count(*) FROM events").fetchone()[0]


def test_driver_t0_path_no_llm():
    conn, bus, registry = _setup()
    # a terminal preceded by a workflow_guard deny -> deterministic T0 antibody candidate, no LLM
    bus.emit_sync("gate_fired", {"gate": "workflow_guard", "decision": "deny", "reason": "workflow_modified",
                  "purpose": "p", "fix": "f"}, correlation_id="c")
    _terminal(bus, "t-deny", "rejected")

    summary = drive(conn, bus, llm_fn=None, idle_millis=0, now_millis=lambda: 5)

    assert "t-deny" in summary["retro_processed"]
    assert summary["maintenance_cycle"] is None  # idle_millis=0 -> no cycle unlocked
    run = conn.execute("SELECT llm_invoked, candidates_emitted_count FROM proj_retro_runs WHERE source_task_id='t-deny'").fetchone()
    assert run[0] == 0 and run[1] == 1  # T0 candidate, LLM not invoked


def test_driver_halts_retro_on_llm_unavailable_leaving_terminals_queued(capsys):
    # rev 0.3.57: a down SDK must not consume the queue as "analyzed, nothing found" — the drive
    # halts the retro drain, leaves every terminal queued for the next window, and still runs the
    # rest of the maintenance pass (cycle/probe/trust/caps).
    from devharness.retro.llm_client import LLMUnavailable

    conn, bus, registry = _setup()
    _terminal(bus, "t-a", "completed")
    _terminal(bus, "t-b", "completed")

    def down_llm(system, ctx, tier):
        raise LLMUnavailable("transport down")

    summary = drive(conn, bus, llm_fn=down_llm, idle_millis=24 * 3600 * 1000, now_millis=lambda: 5)

    assert summary["retro_processed"] == []  # nothing consumed
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='retro_run'").fetchone()[0] == 0
    assert "retro halted: LLM unavailable" in capsys.readouterr().out
    assert summary["adversarial_probe_ran"] is True  # the rest of the pass still ran

    # next window with a healthy LLM drains BOTH terminals
    summary2 = drive(conn, bus, llm_fn=lambda s, c, t: [], idle_millis=24 * 3600 * 1000, now_millis=lambda: 6)
    assert summary2["retro_processed"] == ["t-a", "t-b"]


def test_driver_retro_only_skips_maintenance_probes_and_trust():
    # rev 0.4.23: the backlog-drain mode runs only the learning-spine steps (retro drain + invariant
    # sweep + signal drain) — no maintenance cycle, no adversarial/loop-fault probes, no trust/caps.
    conn, bus, registry = _setup()
    _terminal(bus, "t-clean", "completed")

    fake_llm = lambda system, ctx, tier: []
    summary = drive(conn, bus, llm_fn=fake_llm, idle_millis=24 * 3600 * 1000, now_millis=lambda: 5,
                    retro_only=True)

    assert summary["retro_processed"] == ["t-clean"]  # the drain ran
    assert summary["maintenance_cycle"] is None
    assert summary["adversarial_probe_ran"] is False
    assert summary["loop_fault_ran"] is False
    assert summary["trust"] is None and summary["cap_recommendations"] == []
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='maintenance_cycle_completed'").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='adversarial_probe_run'").fetchone()[0] == 0


def test_driver_reports_held_distinct_from_queue_empty():
    # rev 0.4.23: a non-terminal lifecycle row holds the fermata forever (the exprlang orphan case) —
    # the drive must report held=True so the no-op drain is visible, not silent; queue-empty stays False.
    conn, bus, registry = _setup()
    _terminal(bus, "t-x", "completed")
    # an orphan 'running' lifecycle row with no terminal → FermataPacing.is_held stays True
    bus.emit_sync("task_started", {"task_id": "t-orphan", "role": "developer", "worktree_path": "wt",
                  "started_at_millis": 1, "correlation_id": "c2"}, correlation_id="c2")

    summary = drive(conn, bus, llm_fn=None, idle_millis=0, now_millis=lambda: 5, retro_only=True)
    assert summary["retro_processed"] == [] and summary["retro_held"] is True

    # a clean store with an empty queue is NOT held
    conn2, bus2, _ = _setup()
    summary2 = drive(conn2, bus2, llm_fn=None, idle_millis=0, now_millis=lambda: 5, retro_only=True)
    assert summary2["retro_processed"] == [] and summary2["retro_held"] is False
