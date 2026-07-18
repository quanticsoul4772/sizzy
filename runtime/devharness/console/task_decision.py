"""Operator console task-decision action — accept or reject a retro CANDIDATE at the §S7 review.

The §S7 learning-spine loop ends in a *blocking* operator review (OQ-B5-2=A): a terminal task's
retro produces CANDIDATEs (an antibody or a gate-change) that stay ``pending`` until the operator
explicitly accepts or rejects them — the SOLE path from a CANDIDATE to an enacted change (SC-2, no
auto-apply). The ``devharness retro approve/reject`` CLI is the agent-less driver for that decision;
this surface is the SAME decision pressed from the operator console, with the human in the seat and
no LLM agent making the call:

* ``accept`` approves a pending CANDIDATE through the canonical ``retro.approval.approve_*_candidate``
  — an antibody candidate publishes into the active library, an auto-applicable gate-change enacts —
  recording the decision as the operator-attributed ``candidate_reviewed(approved)`` event
  (``reviewed_by`` = the operator).
* ``reject`` refuses a pending CANDIDATE through ``retro.approval.reject_*_candidate``, recording the
  operator-attributed ``candidate_reviewed(rejected)`` + ``candidate_rejected`` events carrying the
  operator's reason; a blank reason is refused (``EmptyRejectionReason``).

Every decision is recorded through ``EventBus.emit_sync`` — the console's sole sanctioned write path
(the approval functions emit through the supplied bus); the console issues no event-store or
projection write directly, and its ``list_pending`` lookup is SELECT-only. The canonical operation is
used unchanged, so text-only enforcement (Inv 11 — only the structurally-text-only antibody queue can
be approved as an antibody) and the core-gate-unweakable guard (Inv 12) are preserved exactly: the
console adds no path around the approval operation, only the operator seat in front of it.
"""

import time

from devharness.cli.retro import list_pending as _list_pending
from devharness.cli.sign import operator_identity
from devharness.retro.approval import (
    CandidateNotFound,
    approve_antibody_candidate,
    approve_gate_change_candidate,
    reject_antibody_candidate,
    reject_gate_change_candidate,
)

# The two CANDIDATE queues the operator reviews; mirrors the `devharness retro` CLI's choices.
_QUEUES = ("antibody", "gate-change")
_APPROVE = {"antibody": approve_antibody_candidate, "gate-change": approve_gate_change_candidate}
_REJECT = {"antibody": reject_antibody_candidate, "gate-change": reject_gate_change_candidate}


class UnknownQueue(ValueError):
    """Raised when accepting/rejecting against a queue other than 'antibody' or 'gate-change'."""


class EmptyRejectionReason(ValueError):
    """Raised when rejecting a candidate without a reason — a refusal must carry one."""


class ConsoleTaskDecision:
    """Operator-driven accept/reject of a retro CANDIDATE, recorded through ``EventBus.emit_sync``.

    Constructed against the console connection and its ``EventBus`` writer (the emit-only write path).
    ``list_pending`` surfaces the pending CANDIDATEs (SELECT-only); ``accept`` / ``reject`` press the
    operator review decision through the canonical ``retro.approval`` operation, attributing the
    recorded ``candidate_reviewed`` event to the operator. ``operator`` defaults to the harness
    operator identity (``DEVHARNESS_OPERATOR`` env, else ``git config user.name``) and can be
    overridden per instance or per call — mirroring ``ConsoleSignoff`` / ``ConsoleResearch``.
    """

    def __init__(self, conn, writer, *, operator=None, now_millis=None):
        self._conn = conn
        self._writer = writer  # an EventBus — emit_sync is the only sanctioned write path
        self._operator = operator
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))

    def _resolve_operator(self, operator) -> str:
        return operator or self._operator or operator_identity()

    def _resolve_queue(self, queue) -> str:
        q = (queue or "").strip()
        if q not in _APPROVE:
            raise UnknownQueue(
                f"unknown CANDIDATE queue {queue!r}; expected one of {', '.join(_QUEUES)}"
            )
        return q

    def list_pending(self, *, queue="all", limit=50) -> list:
        """Return the pending CANDIDATEs the operator can act on (SELECT-only).

        Delegates to the canonical ``cli.retro.list_pending`` over the console connection; ``queue``
        is ``antibody`` / ``gate-change`` / ``all``. No event-store or projection write.
        """
        return _list_pending(self._conn, queue=queue, limit=limit)

    def accept(self, queue, candidate_row_id, *, operator=None):
        """Accept (approve) a pending CANDIDATE; return the canonical approval's result.

        Routes through ``retro.approval.approve_*_candidate`` for the resolved ``queue`` — publishing
        an antibody into the active library (returns its row id) or enacting an auto-applicable
        gate-change (returns the enacted row id, or ``None`` for an approved-but-advisory change). The
        decision is recorded as the operator-attributed ``candidate_reviewed(approved)`` event.
        Raises ``UnknownQueue`` for an unrecognised queue and ``CandidateNotFound`` for an unknown
        candidate row id.
        """
        q = self._resolve_queue(queue)
        operator = self._resolve_operator(operator)
        return _APPROVE[q](
            candidate_row_id, operator, self._conn, self._writer, now_millis=self._now_millis
        )

    def reject(self, queue, candidate_row_id, reason, *, operator=None) -> int:
        """Reject a pending CANDIDATE with a reason; return the candidate row id.

        Routes through ``retro.approval.reject_*_candidate`` for the resolved ``queue``, recording the
        operator-attributed ``candidate_reviewed(rejected)`` + ``candidate_rejected`` events carrying
        the reason. Raises ``UnknownQueue`` for an unrecognised queue, ``EmptyRejectionReason`` for a
        blank reason, and ``CandidateNotFound`` for an unknown candidate row id.
        """
        q = self._resolve_queue(queue)
        reason = (reason or "").strip()
        if not reason:
            raise EmptyRejectionReason(
                f"rejecting candidate #{candidate_row_id} in {q!r} requires a reason"
            )
        operator = self._resolve_operator(operator)
        _REJECT[q](
            candidate_row_id, operator, reason, self._conn, self._writer, now_millis=self._now_millis
        )
        return candidate_row_id


__all__ = ["ConsoleTaskDecision", "UnknownQueue", "EmptyRejectionReason", "CandidateNotFound"]
