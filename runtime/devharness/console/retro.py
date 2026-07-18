"""Operator console retro-review action — approve or reject a retro CANDIDATE at the §S7 review.

This is the operator console pressing the SAME decision the ``devharness retro`` CLI drives, in the
CLI's own vocabulary (``list-pending`` / ``approve`` / ``reject``): the §S7 learning-spine loop ends in
a *blocking* operator review (OQ-B5-2=A), where a terminal task's retro produces CANDIDATEs (an
antibody or a gate-change) that stay ``pending`` until the operator explicitly approves or rejects them
— the SOLE path from a CANDIDATE to an enacted change (SC-2, no auto-apply). With a human in the seat
and no LLM agent making the call:

* ``approve`` approves a pending CANDIDATE — an antibody candidate publishes into the active library, an
  auto-applicable gate-change enacts — recording the operator-attributed ``candidate_reviewed(approved)``
  event (``reviewed_by`` = the operator).
* ``reject`` refuses a pending CANDIDATE, recording the operator-attributed ``candidate_reviewed(rejected)``
  + ``candidate_rejected`` events carrying the operator's reason; a blank reason is refused
  (``EmptyRejectionReason``).

It is a thin CLI-vocabulary surface over the shared :class:`~devharness.console.task_decision.ConsoleTaskDecision`
operator-review logic — ``approve`` is that surface's ``accept`` under the CLI's name — so the canonical
``retro.approval`` operation is reached unchanged and the same guarantees hold exactly: every decision is
recorded through ``EventBus.emit_sync`` (the console's sole sanctioned write path; no direct event-store or
projection write, and ``list_pending`` is SELECT-only), text-only enforcement (Inv 11 — only the
structurally-text-only antibody queue can be approved as an antibody) and the core-gate-unweakable guard
(Inv 12) are preserved. The console adds no path around the approval operation, only the operator seat in
front of it.
"""

from devharness.console.task_decision import (
    CandidateNotFound,
    ConsoleTaskDecision,
    EmptyRejectionReason,
    UnknownQueue,
)


class ConsoleRetro:
    """Operator-driven approve/reject of a retro CANDIDATE in the ``devharness retro`` CLI's vocabulary.

    Constructed against the console connection and its ``EventBus`` writer (the emit-only write path);
    delegates to the shared :class:`ConsoleTaskDecision` operator-review logic so the canonical
    ``retro.approval`` operation is issued unchanged. ``list_pending`` surfaces the pending CANDIDATEs
    (SELECT-only); ``approve`` / ``reject`` press the operator review decision, attributing the recorded
    ``candidate_reviewed`` event to the operator. ``operator`` defaults to the harness operator identity
    (``DEVHARNESS_OPERATOR`` env, else ``git config user.name``) and can be overridden per instance or per
    call — mirroring the other console action surfaces.
    """

    def __init__(self, conn, writer, *, operator=None, now_millis=None):
        # The shared operator-review logic; ConsoleRetro only renames accept -> approve (the CLI's word).
        self._decision = ConsoleTaskDecision(
            conn, writer, operator=operator, now_millis=now_millis
        )

    def list_pending(self, *, queue="all", limit=50) -> list:
        """Return the pending CANDIDATEs the operator can act on (SELECT-only).

        ``queue`` is ``antibody`` / ``gate-change`` / ``all`` — the same choices as
        ``devharness retro list-pending --queue``. No event-store or projection write.
        """
        return self._decision.list_pending(queue=queue, limit=limit)

    def approve(self, queue, candidate_row_id, *, operator=None):
        """Approve a pending CANDIDATE; return the canonical approval's result.

        The console equivalent of ``devharness retro approve <queue> <id>``: routes through
        ``retro.approval.approve_*_candidate`` for the resolved ``queue`` — publishing an antibody into
        the active library (returns its row id) or enacting an auto-applicable gate-change (returns the
        enacted row id, or ``None`` for an approved-but-advisory change). The decision is recorded as the
        operator-attributed ``candidate_reviewed(approved)`` event. Raises ``UnknownQueue`` for an
        unrecognised queue and ``CandidateNotFound`` for an unknown candidate row id.
        """
        return self._decision.accept(queue, candidate_row_id, operator=operator)

    def reject(self, queue, candidate_row_id, reason, *, operator=None) -> int:
        """Reject a pending CANDIDATE with a reason; return the candidate row id.

        The console equivalent of ``devharness retro reject <queue> <id> --reason TEXT``: routes through
        ``retro.approval.reject_*_candidate`` for the resolved ``queue``, recording the
        operator-attributed ``candidate_reviewed(rejected)`` + ``candidate_rejected`` events carrying the
        reason. Raises ``UnknownQueue`` for an unrecognised queue, ``EmptyRejectionReason`` for a blank
        reason, and ``CandidateNotFound`` for an unknown candidate row id.
        """
        return self._decision.reject(queue, candidate_row_id, reason, operator=operator)


__all__ = ["ConsoleRetro", "UnknownQueue", "EmptyRejectionReason", "CandidateNotFound"]
