"""Drive the §S6 maintenance window + §S7 learning spine + adversarial probes (#H2).

None of the three step-driven schedulers was ever constructed or stepped outside tests — there was no
driver, so the maintenance loop, the learning spine, and the adversarial self-tester never ran on a
real path. This is that driver. One maintenance pass over the event log:

  - **RetroScheduler** with the REAL compositional engine — `RetroEngine(llm_fn=make_llm_fn(parallax))`
    (#H3) — so the §S7 LLM-for-residue path runs live; drains every unprocessed terminal.
  - **MaintenanceScheduler** — runs the deepest cycle the current idle duration unlocks.
  - **AdversarialScheduler** — runs one known-bad probe.

All three are fermata-gated: they yield (run nothing) while a writer holds the single lock or a task
is still live. The retro LLM spends parallax per clean-residue terminal; pass `--no-llm` (or
`DEVHARNESS_RETRO_NO_LLM=1`) for a free T0-only dry run.

Run:  python scripts/run_maintenance.py [--no-llm]  (a stray ANTHROPIC_API_KEY is cleared at startup)
"""

import os
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime"))

from devharness import boot  # noqa: E402
from devharness.mcp.config import MCPConfigError, server_cfg  # noqa: E402
from devharness.adversarial.scheduler import AdversarialScheduler  # noqa: E402
from devharness.faultinjection.scheduler import LoopFaultScheduler  # noqa: E402
from devharness.calibration.evaluation import evaluate_developer_trust  # noqa: E402
from devharness.cli._bus import projected_bus  # noqa: E402
from devharness.maintenance.fermata import FermataPacing  # noqa: E402
from devharness.maintenance.scheduler import MaintenanceScheduler  # noqa: E402
from devharness.migrate import migrate  # noqa: E402
from devharness.monitor.sweep import run_invariant_sweep  # noqa: E402
from devharness.retro.drive import HALT_MESSAGE, HELD_MESSAGE, drain_signal_retro, drain_terminal_retro  # noqa: E402
from devharness.retro.engine import RetroEngine  # noqa: E402
from devharness.models import model_for_tier  # noqa: E402
from devharness.retro.llm_client import make_llm_fn  # noqa: E402
from devharness.retro.scheduler import RetroScheduler  # noqa: E402
from devharness.retro.signal_scheduler import SignalRetroScheduler  # noqa: E402
from devharness.task_classes.ratify import emit_cap_recommendations  # noqa: E402

# a manual maintenance run is the operator deliberately invoking the window — unlock the deepest cycle
_DEFAULT_IDLE_MILLIS = 24 * 3600 * 1000


def drive(conn, event_bus, *, llm_fn, idle_millis=_DEFAULT_IDLE_MILLIS, max_retro=10_000, now_millis=None,
          retro_only=False) -> dict:
    """Run one maintenance pass: drain the retro queue, then one maintenance cycle + one probe.

    Shares a single FermataPacing across the schedulers so all three honour the same hold. `llm_fn`
    is the retro engine's residue analyzer (`make_llm_fn(client)` for live, or `None` for T0-only).
    ``retro_only`` (rev 0.4.23, the backlog-drain mode) runs just the learning-spine steps — terminal
    retro drain + invariant sweep + signal drain — skipping maintenance/adversarial/loop-fault/trust/cap.
    """
    fermata = FermataPacing()
    retro = RetroScheduler(engine=RetroEngine(llm_fn=llm_fn), fermata=fermata)
    # §S7 learning-loop closure: the signal-retro trigger (T0-only — the mapping is deterministic, no
    # residue/LLM) turns invariant_violated / fault_handling_regression into advisory gate-change candidates.
    signal_retro = SignalRetroScheduler(engine=RetroEngine(llm_fn=None), fermata=fermata)

    # rev 0.4.23: the drain loop lives in retro/drive.py (shared with the console auto-drain + TUI/panel
    # actions). The LLMUnavailable halt semantics are unchanged: the analysis never happened — no
    # retro_run was emitted, so the halted terminal (and every later one, including any that would take
    # the LLM-free T0 path) stays queued for the next window. Halting is the fix for the rev-0.3.57
    # burn: a down SDK must not consume the whole queue as "analyzed, nothing found".
    terminal_drain = drain_terminal_retro(conn, event_bus, retro, max_retro=max_retro, now_millis=now_millis)
    if terminal_drain.halted:
        print(f"[run_maintenance] {HALT_MESSAGE} ({terminal_drain.halt_reason})")
    processed = terminal_drain.processed

    if retro_only:
        cycle, probe_ran, loop_fault_ran, trust, cap_recs = None, False, False, None, []
    else:
        maintenance = MaintenanceScheduler(fermata=fermata)
        adversarial = AdversarialScheduler()
        loop_fault = LoopFaultScheduler()
        cycle = maintenance.step(conn, event_bus, idle_millis=idle_millis, now_millis=now_millis)
        probe_ran = adversarial.step(conn, event_bus, fermata, now_millis=now_millis)
        # Loop fault-injection (feature B, rev 0.3.88/0.3.89): inject each real failure class into a hermetic
        # build and let the monitor sweep judge that the harness handled it (one clean terminal, no silent
        # orphan). Fermata-gated; runs the WHOLE probe set per window (rev 0.3.89 — drive() is one process
        # per window, so a per-call cursor would only ever run the first probe). The synthetic builds live in
        # throwaway stores; only the loop_fault_run/fault_handling_regression results reach the live log.
        loop_fault_ran = loop_fault.step(conn, event_bus, fermata, now_millis=now_millis)
        # #H5: measure the developer's live per-class Brier and grant/renew/revoke calibrated trust (SC-5)
        trust = evaluate_developer_trust(conn, event_bus, now_millis=now_millis)
        # #M4: ratify the per-class blast-radius caps from realized telemetry; emit a recommendation per class
        # that crossed the sample threshold (advisory — applying it stays a deliberate operator act)
        cap_recs = emit_cap_recommendations(conn, event_bus, now_millis=now_millis)
    # Live invariant monitor (rev 0.3.87): sweep for behavioral breaches out of band — covers builds not
    # driven through ConsoleDeveloper.dispatch (e.g. the run_developer script path). The sweep self-gates
    # the Inv-10 orphan half on the write lock, so it never false-flags a genuinely in-flight build.
    invariant_violations = run_invariant_sweep(conn, event_bus, now_millis=now_millis)
    # §S7 learning-loop closure: drain this window's (and any prior) invariant_violated / fault_handling_
    # regression signals into operator-review candidates — AFTER the sweep + loop_fault so freshly-emitted
    # signals are caught same-window. Fermata-gated; dedup via proj_signal_retro_runs.
    signal_drain = drain_signal_retro(conn, event_bus, signal_retro, max_signals=max_retro, now_millis=now_millis)
    return {"retro_processed": processed, "maintenance_cycle": cycle, "adversarial_probe_ran": probe_ran,
            "loop_fault_ran": loop_fault_ran, "signals_processed": signal_drain.processed,
            "retro_halted": terminal_drain.halted, "retro_held": terminal_drain.held,
            "trust": trust, "cap_recommendations": cap_recs,
            "invariant_violations": [v.invariant_number for v in invariant_violations]}


def _server_cfg(name: str) -> dict:
    """rev 0.4.25: via the single config source (DEVHARNESS_MCP_CONFIG, else ~/.claude.json)."""
    try:
        return server_cfg(name)
    except MCPConfigError as exc:
        sys.exit(str(exc))


def main() -> int:
    # A stray ANTHROPIC_API_KEY kills the SDK subprocess at launch (exit 1); the harness bills
    # through the claude.ai login. Same posture as the console (tui.py) — rev 0.3.57.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    db_path = os.environ.get("DEVHARNESS_DB") or str(REPO / "var" / "devharness.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    migrate(conn)
    boot.run_boot_checks()  # #C4: fail closed at boot before any work
    bus = projected_bus(conn)

    from devharness.health import emit_snapshot, leak_warning  # resource telemetry (every driver, not just developer)
    snap = emit_snapshot(bus, "maintenance", base_path=str(REPO))
    print(f"[run_maintenance] resources: {snap['process_count']} procs · {snap['git_process_count']} git · "
          f"{snap['worktree_count']} worktrees · {snap['free_memory_mb']}MB free")
    if (warn := leak_warning(snap)):
        print(f"[run_maintenance] ⚠ {warn}")

    no_llm = "--no-llm" in sys.argv or bool(os.environ.get("DEVHARNESS_RETRO_NO_LLM"))
    retro_client = None
    if no_llm:
        llm_fn = None
        print("[run_maintenance] retro residue: T0-only (--no-llm; no parallax spend)")
    else:
        from devharness.mcp.parallax import ParallaxClient
        retro_client = ParallaxClient(mcp_servers={"parallax": _server_cfg("parallax")}, model=model_for_tier("T1"))  # advisory (rev 0.3.82)
        llm_fn = make_llm_fn(retro_client)
        print("[run_maintenance] retro residue: LIVE LLM (make_llm_fn(parallax) — spends per clean-residue terminal)")

    try:
        idle_millis = int(os.environ.get("DEVHARNESS_IDLE_MILLIS", _DEFAULT_IDLE_MILLIS))
    except (TypeError, ValueError):
        idle_millis = _DEFAULT_IDLE_MILLIS
    retro_only = "--retro-only" in sys.argv
    if retro_only:
        print("[run_maintenance] --retro-only: terminal retro drain + invariant sweep + signal drain "
              "(maintenance/adversarial/loop-fault/trust/cap skipped)")
    summary = drive(conn, bus, llm_fn=llm_fn, idle_millis=idle_millis, retro_only=retro_only)

    # SC-6: the retro-residue client's realized spend across every analyzed terminal this pass.
    # Role-scoped (no task_id) — retro analyzes PAST tasks' terminals; per-terminal attribution
    # would mean threading cost deltas through the engine for advisory overhead. Zero emits nothing.
    spent = float(getattr(retro_client, "total_cost_usd", 0) or 0) if retro_client is not None else 0.0
    if spent > 0:
        bus.emit_sync(
            "cost_spent",
            {"role": "retro_residue", "amount_usd": spent,
             "model": getattr(retro_client, "model", "") or "",
             "spent_at_millis": int(time.time() * 1000), "correlation_id": "maintenance"},
            correlation_id="maintenance",
        )

    if summary["retro_held"]:
        # rev 0.4.23: held is NOT queue-empty — a writer lock or a non-terminal lifecycle row (e.g. an
        # orphan 'running' row with no terminal) holds the fermata, and the queue stays intact. Without
        # this line a permanently-held store's backlog drain no-ops in silence.
        print(f"[run_maintenance] {HELD_MESSAGE}")
    print(f"[run_maintenance] retro processed   : {len(summary['retro_processed'])} terminal(s) {summary['retro_processed']}")
    print(f"[run_maintenance] maintenance cycle  : {summary['maintenance_cycle']}")
    print(f"[run_maintenance] adversarial probe  : {'ran' if summary['adversarial_probe_ran'] else 'held/none'}")
    print(f"[run_maintenance] loop-fault probe   : {'ran' if summary['loop_fault_ran'] else 'held/none'}")
    print(f"[run_maintenance] signal-retro drain : {len(summary['signals_processed'])} signal(s) → candidates")
    print(f"[run_maintenance] calibrated trust    : {summary['trust']}")
    recs = summary["cap_recommendations"]
    print(f"[run_maintenance] cap recommendations : {recs if recs else 'none (telemetry below threshold)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
