"""Operator console review/integrate actions — advance the reviewer cert + the integration decision.

The operator drives the back half of the loop directly, with no LLM agent in the seat making the
*review* or *integration* call. ``ConsoleDeveloper.dispatch`` runs the whole write loop in one go
(developer write → verifier acceptance → reviewer cert → integrate); this surface lets the operator
press those last two decisions as discrete steps:

* ``certify`` advances the reviewer certification on a task whose verifier-first acceptance has
  already passed. It runs the SAME fresh-context ``ReviewerRole`` the integrated loop runs — a
  read-only worker (zero write tools, asserted at construction, Invariant 2) that re-verifies the
  task independently and records ``reviewer_certified`` / ``reviewer_rejected`` through the bus. On a
  certification the task is completed via ``done_is_earned.complete``, which re-checks that BOTH a
  verifier pass AND a reviewer certification exist in the current attempt (``completed`` earned
  twice, Invariant 5); on a rejection the task is rejected. The console refuses to advance the review
  step before acceptance has passed (``NotReadyForReview``) — the verifier earn must precede the
  reviewer earn, so Invariant 5's ordering is preserved at the console too.

* ``integrate`` advances the director's integration decision on a task that has reached a terminal
  outcome, routing through the canonical ``roles.integration.integrate`` (it emits the director's
  ``abort`` ``director_decision`` on a non-completed terminal and returns the plan disposition).

Every state change is recorded through ``EventBus.emit_sync`` — the console's sole sanctioned write
path: the reviewer emits its verdict through the supplied bus, ``complete``/``reject`` drive the
terminal through the lifecycle's bus emit, and ``integrate`` emits the director decision through the
bus. The console issues no event-store or projection write directly; its lookups are SELECT-only.
"""

import asyncio
import json
import time

import msgspec

from devharness.console.developer import emit_client_costs
from devharness.events.registry import TerminalOutcome
from devharness.roles.integration import integrate as integrate_terminal
from devharness.roles.reviewer import ReviewerRole
from devharness.task_lifecycle.base import TaskLifecycle, TerminalStates
from devharness.task_lifecycle.done_is_earned import (
    _attempt_start_seq,
    _has_verifier_pass,
    complete,
    reject,
)


class TaskNotStarted(RuntimeError):
    """Raised when reviewing/integrating a task the harness never recorded as started."""


class NotReadyForReview(RuntimeError):
    """Raised when advancing the reviewer step before verifier-first acceptance has passed.

    The reviewer certification is the SECOND earn (Invariant 5); it cannot precede the verifier
    pass. Refusing here keeps the earned-twice ordering explicit at the console.
    """


class AlreadyTerminal(RuntimeError):
    """Raised when reviewing a task that has already reached a terminal outcome."""


class NoTerminalOutcome(RuntimeError):
    """Raised when integrating a task that has not yet reached a terminal outcome."""


class UnknownPlan(RuntimeError):
    """Raised when integrating a task whose dispatching plan cannot be resolved."""


class ConsoleReview:
    """Operator-driven review + integrate actions, recorded through ``EventBus.emit_sync``.

    Constructed against the console connection and its ``EventBus`` writer (the emit-only write
    path). ``certify`` runs the real fresh-context read-only ``ReviewerRole`` and completes/rejects
    the task (``completed`` earned twice, Invariant 5); ``integrate`` advances the director's
    integration decision. The console adds no write path of its own.
    """

    def __init__(self, conn, writer, *, now_millis=None):
        self._conn = conn
        self._writer = writer  # an EventBus — emit_sync is the only sanctioned write path
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))

    # --- reviewer certification (the second earn, Invariant 5) ---

    def certify(self, task_id, *, reviewer=None, parallax=None, context=None, verifiers=None,
                spec_id=None, plan_id=None, lifecycle=None) -> bool:
        """Advance the reviewer certification on ``task_id``; return whether it certified.

        Refuses unless the task has started (``TaskNotStarted``), is non-terminal
        (``AlreadyTerminal``), and its verifier-first acceptance has already passed in the current
        attempt (``NotReadyForReview``) — the verifier earn must precede the reviewer earn
        (Invariant 5). Runs the fresh-context read-only ``ReviewerRole`` (zero write tools, asserted
        at construction, Invariant 2), which records ``reviewer_certified`` / ``reviewer_rejected``
        through the bus. On a certification the task is completed via ``done_is_earned.complete``
        (re-checking the verifier pass AND the reviewer cert both exist — earned twice); on a
        rejection it is rejected. ``reviewer`` injects a pre-built reviewer; otherwise one is built
        from ``parallax`` / ``context`` / ``verifiers``.
        """
        correlation_id = self._correlation_for(task_id)
        if correlation_id is None:
            raise TaskNotStarted(f"task {task_id!r} has no recorded start — nothing to review")
        state = self._current_state(task_id)
        if state in TerminalStates:
            raise AlreadyTerminal(f"task {task_id!r} is already {state!r}; cannot review it again")
        since = _attempt_start_seq(self._conn, task_id)
        if not _has_verifier_pass(self._conn, task_id, since):
            raise NotReadyForReview(
                f"task {task_id!r} has no verifier pass in the current attempt — "
                "verifier-first acceptance must pass before the reviewer certifies (Invariant 5)"
            )

        spec_id = spec_id or self._latest_signed_spec(correlation_id)
        plan_id = plan_id or self._plan_for(task_id)
        reviewer = reviewer or self.build_reviewer(
            correlation_id, parallax=parallax, context=context, verifiers=verifiers
        )

        certified = asyncio.run(reviewer.run(task_id, spec_id, plan_id, correlation_id))

        # SC-6 (rev 0.4.2): the certify action's reviewer client spends real (frontier) tokens but had
        # NO cost_spent emission — the dispatch loop's verify_review emission never fires on this
        # manually-advanced path. Billed here with the client's model, before complete/reject emit the
        # terminal (the dispatch loop's normal path bills AFTER its terminal — harmless skew: no retro
        # predicate keys on cost_spent in preceding_events). Zero-cost (stubbed) reviewers emit nothing.
        emit_client_costs(self._writer, [getattr(reviewer, "parallax", None)], role="verify_review",
                          correlation_id=correlation_id, task_id=task_id,
                          now_millis=self._now_millis)

        lifecycle = lifecycle or self._seed_lifecycle(task_id, state)
        if certified:
            complete(task_id, lifecycle, self._conn, self._writer, now_millis=self._now_millis)
        else:
            reject(task_id, "reviewer rejected", lifecycle, self._conn, self._writer,
                   now_millis=self._now_millis)
        return certified

    def build_reviewer(self, correlation_id, *, parallax=None, context=None, verifiers=None) -> ReviewerRole:
        """Build the fresh-context read-only ``ReviewerRole`` the certification runs.

        Zero write tools are asserted at construction (Invariant 2); the bus the reviewer records
        its verdict through is the console's emit-only writer. ``parallax`` defaults to the live
        client; ``context`` defaults to the reviewer's own harness-assembled context.
        """
        if parallax is None:
            from devharness.console.developer import live_parallax_client

            parallax = live_parallax_client()
        if context is None:
            context = ReviewerRole.assemble_context(self._conn, correlation_id)
        return ReviewerRole(
            parallax=parallax, event_bus=self._writer, conn=self._conn,
            context=dict(context, prior_events=[]), fresh_context=True, verifiers=verifiers,
            now_millis=self._now_millis,
        )

    # --- director integration decision ---

    def integrate(self, task_id, *, terminal_outcome=None, plan_id=None) -> str:
        """Advance the director's integration decision on a terminal task; return the disposition.

        Resolves the task's terminal outcome (``NoTerminalOutcome`` if none) and its dispatching
        plan (``UnknownPlan`` if none), then routes through the canonical
        ``roles.integration.integrate`` — which emits the director's ``abort`` ``director_decision``
        through the bus on a non-completed terminal and returns ``'completed'`` (advance) or
        ``'blocked'`` (stop).
        """
        terminal_outcome = terminal_outcome or self._terminal_outcome(task_id)
        if terminal_outcome is None:
            raise NoTerminalOutcome(
                f"task {task_id!r} has no terminal outcome — nothing to integrate"
            )
        plan_id = plan_id or self._plan_for(task_id)
        if plan_id is None:
            raise UnknownPlan(f"task {task_id!r} was not dispatched under a known plan")
        return integrate_terminal(plan_id, task_id, terminal_outcome, self._conn, self._writer)

    # --- read-only lookups (SELECT-only; no event-store or projection writes) ---

    def _correlation_for(self, task_id):
        row = self._conn.execute(
            "SELECT correlation_id FROM proj_task_started WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row[0] if row else None

    def _current_state(self, task_id):
        row = self._conn.execute(
            "SELECT current_state FROM proj_task_lifecycle WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row[0] if row else None

    def _seed_lifecycle(self, task_id, state):
        """A ``TaskLifecycle`` whose in-process state matches the projection — so a standalone
        console action transitions from the task's ACTUAL current state, not the 'queued' default."""
        lifecycle = TaskLifecycle()
        lifecycle._state[task_id] = state or "running"
        return lifecycle

    def _plan_for(self, task_id):
        row = self._conn.execute(
            "SELECT plan_id FROM proj_task_dispatched WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row[0] if row else None

    def _terminal_outcome(self, task_id):
        latest = None
        for (payload,) in self._conn.execute(
            "SELECT payload FROM events WHERE event_type = 'terminal_outcome' ORDER BY seq"
        ):
            record = json.loads(payload)
            if record.get("task_id") == task_id:
                latest = record
        if latest is None:
            return None
        return msgspec.convert(latest, TerminalOutcome, strict=False)

    def _latest_signed_spec(self, correlation_id):
        row = self._conn.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE artifact_type = 'spec' AND correlation_id = ? AND signed = 1 "
            "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1",
            (correlation_id,),
        ).fetchone()
        return row[0] if row else None
