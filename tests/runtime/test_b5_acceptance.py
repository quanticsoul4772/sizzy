"""B5.7 cut-line acceptance — the full learning-spine loop, end to end.

terminal_outcome → RetroScheduler → retro engine (T0 + LLM-for-residue) → CANDIDATE (pending) →
operator approve/reject → antibody_added → memory_entry_created (bridge) → export → import → verify.

Exercises Inv 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18 across the loop (see the per-assertion
comments). Inv 12 + SC-2 + A-OP-3 + A-SYS-5 are exercised in test_b5_assertions.py.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.events.bus import EventBus, verify_chain
from devharness.migrate import migrate
from devharness.memory.export_import import export_memory, import_memory
from devharness.memory.store import list_verified_memory, verify_memory_entry
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.approval import approve_antibody_candidate, reject_gate_change_candidate
from devharness.retro.engine import RetroEngine
from devharness.retro.scheduler import RetroScheduler


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, registry, EventBus(conn, registry)


def _gate_fired(bus, gate, decision, reason, cid):
    bus.emit_sync("gate_fired", {"gate": gate, "decision": decision, "reason": reason,
                  "purpose": "p", "fix": ""}, correlation_id=cid)


def _intake_decision(bus, decision, rejection_reason, cid):
    bus.emit_sync("intake_decision", {"intake_correlation_id": cid, "decision": decision,
                  "rejection_reason": rejection_reason, "detected_patterns": [], "decision_at_millis": 1,
                  "correlation_id": cid}, correlation_id=cid)


def _verifier_outcome(bus, task_id, passed, detail, cid):
    # realistic shape (rev 0.4.23): the T0 verifier_failure signatures now require the structured
    # verifier name + the terminal's own task_id + an "<axis> axis failed" detail prefix
    bus.emit_sync("verifier_outcome", {"task_id": task_id, "verifier": "bugfix_regression", "passed": passed,
                  "detail": detail, "evidence": {}}, correlation_id=cid)


def _budget_exceeded(bus, budget_kind, cid):
    bus.emit_sync("budget_exceeded", {"budget_kind": budget_kind, "role": "developer", "limit": "wall",
                  "spent": "9", "limit_value": 1.0, "observed_value": 9.0, "action_taken": "abort",
                  "subject_id": "task", "reason": "cap_exceeded", "exceeded_at_millis": 1,
                  "correlation_id": cid}, correlation_id=cid)


def _terminal(bus, task_id, outcome, cid):
    bus.emit_sync("terminal_outcome", {"task_id": task_id, "outcome": outcome, "detail": "", "reason": "",
                  "correlation_id": cid, "terminated_at_millis": 1}, correlation_id=cid)


def _llm_fn(_sp, _ctx, _tier):
    # deterministic mocked LLM: one novel antibody from a T0-empty clean residue
    return [{"kind": "antibody_candidate", "signature_name": "llm_novel", "pattern_text": "llm-novel-residue"}]


def _drive_retro(conn, bus):
    """Run the scheduler to drain every terminal through the compositional engine."""
    sched = RetroScheduler(engine=RetroEngine(llm_fn=_llm_fn))
    n = 0
    while sched.step(conn, bus, now_millis=lambda: 100 + n) is not None:
        n += 1
    return n


def test_full_learning_loop_end_to_end(monkeypatch):
    conn, registry, bus = _setup()

    # 4 terminals with varied terminal_kind + preceding events that fire known signatures
    _gate_fired(bus, "workflow_guard", "deny", "workflow modification denied at admission", "task-a")
    _terminal(bus, "task-a", "completed", "task-a")  # → antibody (gate_deny_workflow_modified)

    _intake_decision(bus, "rejected", "injection_detected", "task-b")
    _terminal(bus, "task-b", "rejected", "task-b")  # → antibody (intake_reject_injection)

    _budget_exceeded(bus, "oss_wall_clock", "task-c")
    _verifier_outcome(bus, "task-c", False,
                      "baseline_should_fail axis failed: the regression test passed at baseline", "task-c")
    _terminal(bus, "task-c", "aborted", "task-c")  # → 2 gate_change (cap_exceeded + verifier_failure, the B5.7 fix)

    _terminal(bus, "task-d", "completed", "task-d")  # no T0 match, clean → LLM residue → antibody

    processed = _drive_retro(conn, bus)
    assert processed == 4  # every terminal got exactly one retro_run (Inv 10: one terminal per task)
    assert conn.execute("SELECT count(*) FROM proj_retro_runs").fetchone()[0] == 4

    # CANDIDATEs landed pending (SC-2: no auto-apply) across both queues
    antibody_pending = conn.execute("SELECT count(*) FROM proj_antibody_queue WHERE review_state='pending'").fetchone()[0]
    gate_pending = conn.execute("SELECT count(*) FROM proj_gate_change_queue WHERE review_state='pending'").fetchone()[0]
    assert antibody_pending == 3  # gate_deny + intake_reject + llm_novel
    assert gate_pending == 2  # cap_exceeded + verifier_failure_baseline_fail (the fixed signature fired)
    # the LLM path ran exactly once (only task-d had a T0-empty clean residue)
    assert conn.execute("SELECT count(*) FROM proj_retro_runs WHERE llm_invoked=1").fetchone()[0] == 1

    # operator APPROVES one antibody → CandidateReviewed(approved) + antibody_added + memory bridge
    cand = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue WHERE review_state='pending' ORDER BY antibody_row_id LIMIT 1").fetchone()[0]
    approve_antibody_candidate(cand, "operator", conn, bus, now_millis=lambda: 200)
    assert conn.execute("SELECT review_state FROM proj_antibody_queue WHERE antibody_row_id=?", (cand,)).fetchone()[0] == "approved"
    assert conn.execute("SELECT count(*) FROM proj_antibody_library").fetchone()[0] == 1  # Inv 5: earned via review
    mem = conn.execute("SELECT entry_type, source_project, verified_locally FROM proj_memory").fetchone()
    assert mem == ("antibody", "devharness", 1)  # bridge: local + trusted (Inv 17 local case)

    # operator REJECTS one gate-change → no enactment, nothing published
    gc = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue WHERE review_state='pending' ORDER BY gate_change_row_id LIMIT 1").fetchone()[0]
    reject_gate_change_candidate(gc, "operator", "not worth tightening", conn, bus, now_millis=lambda: 201)
    assert conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE gate_change_row_id=?", (gc,)).fetchone()[0] == "rejected"

    # project A's spine invariants — checked BEFORE the sibling flips the project identity (proj_memory's
    # local-vs-imported handler reads project_name(), which must be stable for A's rebuild to reproduce).
    # Inv 7: every event carries a correlation_id. Inv 9: the hash chain validates over the whole log.
    assert boot.check_correlation_id_coverage(conn) is True
    assert verify_chain(conn) == conn.execute("SELECT count(*) FROM events").fetchone()[0]
    # Inv 8: DELETE+replay rebuild reproduces every projection (all 32 tile feeds)
    assert check_projection_rebuild_parity(conn, registry) is True

    # cross-project memory sync: export → import into a SIBLING project (different identity, fresh DB)
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "mem.json")
        assert export_memory(path, conn) == 1
        # the sibling is a different project: the entry's source_project ('devharness') is foreign there
        monkeypatch.setenv("DEVHARNESS_PROJECT_NAME", "sibling-project")
        conn2, registry2, bus2 = _setup()
        assert import_memory(path, conn2, bus2) == 1
        imported = conn2.execute("SELECT entry_id, verified_locally FROM proj_memory").fetchone()
        assert imported[1] == 0  # Inv 17: imported entries untrusted until locally re-verified
        assert list_verified_memory(conn2) == []
        verify_memory_entry(imported[0], {"verifier": "feature_spec_claim"}, "operator", conn2, bus2, now_millis=lambda: 300)
        assert [e.entry_id for e in list_verified_memory(conn2)] == [imported[0]]  # now trusted
        # the sibling's own spine rebuilds cleanly under its identity (Inv 8 across import + verify)
        assert check_projection_rebuild_parity(conn2, registry2) is True


def test_boot_ledger_and_audit_affirmed():
    # Inv 18: the 24-name boot ledger is fully real; C7 tile coverage holds at 32
    assert len(boot.registered_check_names()) == len(boot.REQUIRED_GATES)
    real = sum(1 for checks in boot._REGISTRY.values() for fn in checks.values() if fn is not boot._unmapped)
    assert real == len(boot.registered_check_names())  # 0 stubs
    assert boot.check_dashboard_tile_coverage() is True
    # full invariant graduation: the three B5 invariant checks are all real + pass
    assert boot.check_inv_11_antibodies_text_only() is True
    assert boot.check_inv_12_core_gates_unweakable() is True
    assert boot.check_inv_17_verified_before_trusted() is True
