"""Signal-retro scheduler (§S7 learning-loop closure).

The terminal-triggered ``RetroScheduler`` can only see events in a terminal's ``preceding_events``
(same correlation, ``seq < terminal``). Two signals are unreachable that way:
``fault_handling_regression`` has correlation ``"fault-injection"`` with no live terminal at all, and
``invariant_violated`` is always emitted at a higher seq than the terminal it concerns (and carries the
real BUILD correlation for the per-build checks, only falling back to ``"monitor"`` for chain/empty-corr
checks — which is exactly why the two signatures are signal-gated in ``t0_matcher``, so the terminal path
never re-fires them from a re-driven terminal's preceding_events). This scheduler is the trigger for those
two: it drains ``invariant_violated`` /
``fault_handling_regression`` events directly, builds a ``RetroContext`` carrying the signal event, and
reuses the existing ``RetroEngine`` T0 path (the ``monitor_invariant_violated`` / ``loop_fault_regression``
signatures) → an advisory ``gate_change_candidate`` in the operator-review queue.

Fermata-gated + step-driven like ``RetroScheduler``; ``proj_signal_retro_runs`` (keyed on the signal's
own ``event_id``) is the dedup ledger — a signal with a row there is never re-analyzed.
"""

import json
import time

import msgspec

from devharness.events.registry import SignalRetroRun
from devharness.maintenance.fermata import FermataPacing
from devharness.retro.base import RetroContext

# The two signal types this scheduler drains. NOTE: a new entry here MUST also get a matching t0_matcher
# signature (monitor_invariant_violated / loop_fault_regression) — a signal that matches no signature drains
# to zero candidates and is still marked processed (silently dropped).
_SIGNAL_EVENT_TYPES = ("invariant_violated", "fault_handling_regression")

# event_type -> the target_gate its signature emits; used by the open-candidate guard to collapse repeated
# same-category signals into one pending review item (must stay in sync with the t0_matcher templates).
_SIGNAL_TARGET_GATE = {
    "invariant_violated": "invariant_monitor",
    "fault_handling_regression": "fault_handling",
}


class SignalRetroScheduler:
    def __init__(self, engine, fermata=None):
        self.engine = engine  # a RetroEngine; the mapping is deterministic (T0), so llm_fn=None is fine
        self.fermata = fermata or FermataPacing()

    def _next_unprocessed_signal(self, conn):
        """The earliest signal event (either type) with no proj_signal_retro_runs row yet."""
        return conn.execute(
            "SELECT e.event_id, e.event_type, e.correlation_id, e.payload FROM events e "
            "LEFT JOIN proj_signal_retro_runs r ON r.signal_event_id = e.event_id "
            "WHERE e.event_type IN ('invariant_violated', 'fault_handling_regression') "
            "AND r.signal_event_id IS NULL ORDER BY e.seq LIMIT 1"
        ).fetchone()

    def step(self, conn, event_bus, *, now_millis=None) -> str | None:
        """Process at most one signal into candidates. Returns the processed event_id, or None if held /
        nothing unprocessed."""
        if self.fermata.is_held(conn):
            return None
        row = self._next_unprocessed_signal(conn)
        if row is None:
            return None
        event_id, event_type, correlation_id, payload_json = row
        payload = json.loads(payload_json)
        at = (now_millis or (lambda: int(time.time() * 1000)))()

        # Open-candidate guard: a persistently-regressing fault emits a FRESH fault_handling_regression
        # (new event_id) every maintenance window; the event-id-keyed ledger would otherwise create a new
        # pending candidate each window (unbounded queue). And because the candidate is emitted before the
        # ledger row, a crash between the two commits re-drains the signal → a duplicate. So if a PENDING
        # gate_change_candidate already exists for this signal's target_gate, mark the signal processed with
        # zero candidates and skip re-emitting. Once the operator reviews the open candidate (no longer
        # 'pending'), the next signal creates a fresh one. Coarse (per target_gate) — acceptable v1.
        target_gate = _SIGNAL_TARGET_GATE.get(event_type)
        already_open = target_gate is not None and conn.execute(
            "SELECT 1 FROM proj_gate_change_queue WHERE target_gate = ? AND review_state = 'pending' LIMIT 1",
            (target_gate,),
        ).fetchone() is not None

        if already_open:
            candidates_emitted_count, candidate_kinds = 0, []
        else:
            ctx = RetroContext(
                terminal_outcome_event={},
                preceding_events=[{"event_id": event_id, "event_type": event_type, "payload": payload}],
                calibration_snapshot={},
                source_task_id=payload.get("task_id", "") or "",
                correlation_id=correlation_id,
            )
            result = self.engine.analyze(ctx, event_bus, now_millis=lambda: at)
            candidates_emitted_count = len(result.candidates_emitted)
            candidate_kinds = list(result.candidate_kinds)

        event_bus.emit_sync(
            "signal_retro_run",
            msgspec.to_builtins(SignalRetroRun(
                signal_event_id=event_id, signal_event_type=event_type,
                candidates_emitted_count=candidates_emitted_count, candidate_kinds=candidate_kinds,
                correlation_id=correlation_id, run_at_millis=at,
            )),
            correlation_id=correlation_id,
        )
        return event_id
