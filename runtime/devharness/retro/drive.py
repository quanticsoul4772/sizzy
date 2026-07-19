"""Shared retro drain loops (§S7, rev 0.4.23).

Extracted from ``scripts/run_maintenance.drive`` so retro runs where builds happen: the maintenance
driver, the console post-build auto-drain (``ConsoleDeveloper.dispatch``), the TUI ``L`` action, and
the panel ``/retro/run`` route all call these two functions instead of hand-rolling the step loop.

Both preserve the ``LLMUnavailable`` halt semantics (rev 0.3.57): a down SDK stops the drain and
leaves the remaining terminals queued — it must never consume the queue as "analyzed, nothing found".
``held`` is reported distinctly from queue-empty: a store whose fermata is held (writer lock or a
non-terminal lifecycle row — e.g. an orphan ``running`` row with no terminal) drains 0 forever, and
without the distinction that no-ops in silence. No printing here — callers own their surface (stdout
for the script, the log pane for the TUI); they render from the returned shape.

Accepted residual (documented, not fixed): with the post-build auto-drain live, TWO processes can
drain one store concurrently (a panel/TUI dispatch finishing while a run_maintenance window drains).
The per-terminal dedup (read ``proj_retro_runs`` → analyze → emit ``retro_run``) is not atomic
across processes, so a racing pair can double-analyze one terminal — double T1 residue spend and a
duplicate candidate, both bounded and both landing in the BLOCKING operator review queue (SC-2), so
the noise is visible and rejectable, never auto-applied. A cross-process drain mutex is deliberately
not built for an advisory spine; revisit if real double-analysis shows up in review queues.
"""

import msgspec

from devharness.retro.llm_client import LLMUnavailable

# The two operator-facing lines, shared by every drain surface (run_maintenance prints, the TUI/panel
# summary, the auto-drain's stderr) so the wording can't drift across the three renderers.
HELD_MESSAGE = "retro drain HELD (fermata: writer lock or non-terminal lifecycle row) — 0 processed, queue intact"
HALT_MESSAGE = "retro halted: LLM unavailable — terminals left queued"


class DrainResult(msgspec.Struct, frozen=True, kw_only=True):
    processed: list  # task_ids (terminal drain) / signal event_ids (signal drain), in drain order
    halted: bool = False  # LLMUnavailable stopped the drain; the rest of the queue is intact
    halt_reason: str = ""  # the LLMUnavailable message when halted
    held: bool = False  # the fermata was held and nothing was processed — distinct from queue-empty


def _drain(conn, event_bus, scheduler, *, max_steps, now_millis) -> DrainResult:
    # held is sampled BEFORE the loop (review catch: a post-loop re-check is a TOCTOU against other
    # processes on the store — the hold that made step() return None can release before the re-check,
    # reporting a plain "0 processed" for an intact queue, the exact silent no-op held exists to name).
    held_at_start = scheduler.fermata.is_held(conn)
    processed = []
    halted = False
    halt_reason = ""
    for _ in range(max_steps):
        try:
            step_id = scheduler.step(conn, event_bus, now_millis=now_millis)
        except LLMUnavailable as exc:
            halted = True
            halt_reason = str(exc)
            break
        if step_id is None:
            break
        processed.append(step_id)
    held = not processed and not halted and held_at_start
    return DrainResult(processed=processed, halted=halted, halt_reason=halt_reason, held=held)


def drain_terminal_retro(conn, event_bus, retro_scheduler, *, max_retro=10_000, now_millis=None) -> DrainResult:
    """Drain every unprocessed terminal through the scheduler's engine (T0 + LLM residue)."""
    return _drain(conn, event_bus, retro_scheduler, max_steps=max_retro, now_millis=now_millis)


def drain_signal_retro(conn, event_bus, signal_scheduler, *, max_signals=10_000, now_millis=None) -> DrainResult:
    """Drain every unprocessed invariant_violated / fault_handling_regression signal (T0-only, free)."""
    return _drain(conn, event_bus, signal_scheduler, max_steps=max_signals, now_millis=now_millis)
