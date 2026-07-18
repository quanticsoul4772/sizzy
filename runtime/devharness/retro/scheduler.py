"""Retro scheduler (B5.0, §S7).

Drives the retro auditor one step at a time inside the B3.6 maintenance window (yields under the
fermata — never runs while a writer holds the lock or a task is live). The terminal-outcome queue is
event-log-derived: the earliest `terminal_outcome` whose (task, kind) has no `retro_run` yet (keyed on
(task_id, terminal_kind) so a re-driven task's later, different-kind terminal — reject→complete — is
still analyzed). Per OQ-B5-1 (resolved A, revisitable) the queue includes completed AND rejected AND
aborted terminals — to drop to the rejected/aborted subset later, narrow the `IN (...)` filter below.

The engine is injected (B5.1 implements the compositional T0 + LLM-for-residue engine, OQ-B5-4=C);
B5.0 runs with no engine and emits a stub `retro_run`.
"""

import json
import time

import msgspec

from devharness.calibration.brier import compute_brier_for_role
from devharness.events.registry import RetroRun
from devharness.maintenance.fermata import FermataPacing
from devharness.retro.base import RetroContext, RetroResult

_TERMINAL_KINDS = ("completed", "rejected", "aborted")  # OQ-B5-1=A: every terminal kind


class RetroScheduler:
    def __init__(self, engine=None, fermata=None):
        self.engine = engine  # B5.1 supplies the compositional engine; None -> B5.0 stub
        self.fermata = fermata or FermataPacing()

    def _next_unprocessed(self, conn):
        """The earliest terminal_outcome (any of the three kinds) with no retro_run for its (task, kind) yet.

        Dedup is keyed on (source_task_id, terminal_kind), NOT task_id alone: a re-driven task emits a
        SECOND terminal_outcome (e.g. reject → operator re-drive → complete), and keying on task_id alone
        excluded that later, different-kind terminal forever, so the learning spine permanently saw only
        the first (rejected) outcome. Keying on (task, kind) lets the completion be analyzed. proj_retro_runs
        already records terminal_kind, so this is a read-side query change with no migration; Inv 8 parity
        is unaffected (the queue is event-log-derived). Residual: two SAME-kind terminals for one task —
        only the first is analyzed (a same-kind re-terminal carries largely the same advisory signal)."""
        return conn.execute(
            "SELECT e.seq, e.correlation_id, e.payload FROM events e "
            "LEFT JOIN proj_retro_runs r ON r.source_task_id = json_extract(e.payload, '$.task_id') "
            "AND r.terminal_kind = json_extract(e.payload, '$.outcome') "
            "WHERE e.event_type = 'terminal_outcome' "
            "AND json_extract(e.payload, '$.outcome') IN ('completed', 'rejected', 'aborted') "
            "AND r.retro_row_id IS NULL ORDER BY e.seq LIMIT 1"
        ).fetchone()

    def _build_context(self, conn, terminal_seq, terminal_payload, correlation_id) -> RetroContext:
        task_id = terminal_payload["task_id"]
        # preceding events carry event_id + event_type so T0 predicates can filter + cite evidence
        preceding = [
            {"event_id": eid, "event_type": etype, "payload": json.loads(p)}
            for (eid, etype, p) in conn.execute(
                "SELECT event_id, event_type, payload FROM events WHERE correlation_id = ? AND seq < ? ORDER BY seq",
                (correlation_id, terminal_seq),
            )
        ]
        vo = conn.execute(
            "SELECT payload FROM events WHERE event_type='verifier_outcome' "
            "AND json_extract(payload,'$.task_id') = ? ORDER BY seq DESC LIMIT 1", (task_id,)
        ).fetchone()
        rc = conn.execute(
            "SELECT payload FROM events WHERE event_type='reviewer_certified' "
            "AND json_extract(payload,'$.task_id') = ? ORDER BY seq DESC LIMIT 1", (task_id,)
        ).fetchone()
        return RetroContext(
            terminal_outcome_event=terminal_payload, preceding_events=preceding,
            calibration_snapshot=self._calibration_snapshot(conn, task_id),
            source_task_id=task_id, correlation_id=correlation_id,
            verifier_outcome=json.loads(vo[0]) if vo else None,
            reviewer_certification=json.loads(rc[0]) if rc else None,
        )

    def _calibration_snapshot(self, conn, task_id) -> dict:
        """#H4: carry the developer's live per-class Brier so the calibration_brier_drift signature can
        fire (it was always `{}`, so `_brier_drift` was unreachable). The class is the terminal task's
        dispatched class; below min_samples (no live Brier) the snapshot is empty — no false drift."""
        row = conn.execute(
            "SELECT json_extract(payload, '$.task_class') FROM events WHERE event_type = 'task_dispatched' "
            "AND json_extract(payload, '$.task_id') = ? ORDER BY seq DESC LIMIT 1", (task_id,)
        ).fetchone()
        task_class = row[0] if row and row[0] else None
        if not task_class:
            return {}
        brier = compute_brier_for_role("developer", task_class, conn)
        return {"brier": brier} if brier is not None else {}

    def step(self, conn, event_bus, *, now_millis=None) -> str | None:
        """Process at most one terminal. Returns the processed task_id, or None if held / queue empty."""
        if self.fermata.is_held(conn):
            return None
        row = self._next_unprocessed(conn)
        if row is None:
            return None
        terminal_seq, correlation_id, payload_json = row
        terminal_payload = json.loads(payload_json)
        ctx = self._build_context(conn, terminal_seq, terminal_payload, correlation_id)

        at = (now_millis or (lambda: int(time.time() * 1000)))()
        if self.engine is not None:
            # the engine emits the CANDIDATE events itself; the scheduler folds its run shape into retro_run
            result = self.engine.analyze(ctx, event_bus, now_millis=lambda: at)
        else:
            result = RetroResult(candidates_emitted=[], summary="b5.0_stub")  # B5.0: no engine wired
        event_bus.emit_sync(
            "retro_run",
            msgspec.to_builtins(RetroRun(
                terminal_outcome_correlation_id=correlation_id, source_task_id=ctx.source_task_id,
                terminal_kind=terminal_payload["outcome"], t0_matched_signatures=list(result.t0_matched_signatures),
                llm_invoked=result.llm_invoked, candidates_emitted_count=len(result.candidates_emitted),
                candidate_kinds=list(result.candidate_kinds), retro_run_at_millis=at, correlation_id=correlation_id,
            )),
            correlation_id=correlation_id,
        )
        return ctx.source_task_id
