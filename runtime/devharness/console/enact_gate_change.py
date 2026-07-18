"""Operator console gate-change enactment action — enact an APPROVED gate-change candidate (§S7).

The §S7 learning spine's gate-change half ends in an ENACTMENT: an approved, auto-applicable gate-change
takes effect by recording into ``proj_enacted_gate_changes`` via the ``gate_change_enacted`` event — the
only enactment path (``retro.enacted_gate_changes.enact_gate_change``), the gate-change analogue of
``antibody_added``. This surface is the SAME enactment pressed from the operator console, with a human in
the seat and no LLM agent making the call:

* ``list_approved`` surfaces the approved gate-change candidates the operator can enact (SELECT-only),
  each carrying an ``enactable`` flag (today only an ``add_signature`` with a non-empty signature is
  auto-applicable; ``tighten``/``loosen`` are approved-but-advisory operator signals with no concretely
  auto-applicable parameter). No event-store or projection write.
* ``enact`` issues the canonical ``retro.enacted_gate_changes.enact_gate_change`` operation for an
  approved candidate, recording the operator-attributed ``gate_change_enacted`` event (the operator is the
  ``enacted_by`` authorizer). It refuses a candidate that is not ``approved`` (``GateChangeNotApproved``)
  and an unknown candidate row id (``CandidateNotFound``).

The enactment is recorded through ``EventBus.emit_sync`` — the console's sole sanctioned write path (the
canonical operation emits through the supplied bus); the console issues no event-store or projection write
directly, and ``list_approved`` is SELECT-only. The canonical operation is used unchanged, so its
guarantees hold exactly: **Invariant 12 still refuses any core-gate weakening** — ``enact_gate_change``
re-checks ``would_weaken_core_gate`` and raises before any event is emitted, so even a hand-built approved
core-gate-weakening row can never be enacted from this surface; and a non-auto-applicable change is refused
(``is_enactable``) so no inert or arbitrary row is ever recorded. The console adds no path around the
enactment operation, only the operator seat in front of it.
"""

import json
import time

from devharness.cli.sign import operator_identity
from devharness.retro.approval import CandidateNotFound
from devharness.retro.enacted_gate_changes import enact_gate_change, is_enactable


class GateChangeNotApproved(ValueError):
    """Raised when enacting a gate-change candidate that is not in the ``approved`` review state.

    Only an operator-approved candidate may be enacted — a pending one has not been reviewed and a
    rejected one was refused; enacting either would bypass the §S7 operator-review gate (SC-2).
    """


class ConsoleEnactGateChange:
    """Operator-driven enactment of an approved gate-change candidate, recorded through ``EventBus.emit_sync``.

    Constructed against the console connection and its ``EventBus`` writer (the emit-only write path).
    ``list_approved`` surfaces the approved candidates an operator could enact (SELECT-only); ``enact``
    presses the canonical ``retro.enacted_gate_changes.enact_gate_change`` operation, attributing the
    recorded ``gate_change_enacted`` event to the operator. ``operator`` defaults to the harness operator
    identity (``DEVHARNESS_OPERATOR`` env, else ``git config user.name``) and can be overridden per
    instance or per call — mirroring ``ConsolePrune`` / ``ConsoleTaskDecision``.
    """

    def __init__(self, conn, writer, *, operator=None, now_millis=None):
        self._conn = conn
        self._writer = writer  # an EventBus — emit_sync is the only sanctioned write path
        self._operator = operator
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))

    def _resolve_operator(self, operator) -> str:
        return operator or self._operator or operator_identity()

    def list_approved(self, *, limit=50) -> list:
        """Return the approved gate-change candidates the operator can enact (SELECT-only).

        Each row is ``{gate_change_row_id, target_gate, change_kind, change_details, enactable}`` — the
        ``enactable`` flag is the canonical ``is_enactable`` verdict (today only an ``add_signature`` with
        a non-empty signature is auto-applicable). No event-store or projection write.
        """
        rows = self._conn.execute(
            "SELECT gate_change_row_id, target_gate, change_kind, change_details_json "
            "FROM proj_gate_change_queue WHERE review_state = 'approved' "
            "ORDER BY gate_change_row_id LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for row_id, target_gate, change_kind, details_json in rows:
            details = json.loads(details_json) if details_json else {}
            out.append({
                "gate_change_row_id": row_id,
                "target_gate": target_gate,
                "change_kind": change_kind,
                "change_details": details,
                "enactable": is_enactable(target_gate, change_kind, details),
            })
        return out

    def enact(self, candidate_row_id, *, operator=None) -> int:
        """Enact an approved gate-change candidate; return the enacted_row_id.

        Routes through the canonical ``retro.enacted_gate_changes.enact_gate_change`` for the candidate,
        recording the operator-attributed ``gate_change_enacted`` event (the operator is ``enacted_by``).
        Refuses a candidate that is not ``approved`` (``GateChangeNotApproved``) and an unknown candidate
        row id (``CandidateNotFound``). The canonical operation re-checks Inv 12 (a core-gate weakening is
        never enacted) and ``is_enactable`` (a non-auto-applicable change is refused) before any event is
        emitted.
        """
        row = self._conn.execute(
            "SELECT target_gate, change_kind, change_details_json, retro_run_correlation_id, review_state "
            "FROM proj_gate_change_queue WHERE gate_change_row_id = ?",
            (candidate_row_id,),
        ).fetchone()
        if row is None:
            raise CandidateNotFound(f"no gate-change candidate with row id {candidate_row_id}")
        target_gate, change_kind, details_json, cid, review_state = row
        if review_state != "approved":
            raise GateChangeNotApproved(
                f"gate-change candidate #{candidate_row_id} is {review_state!r}, not 'approved' — "
                "only an operator-approved candidate may be enacted"
            )
        details = json.loads(details_json) if details_json else {}
        operator = self._resolve_operator(operator)
        cid = cid or "operator_review"
        return enact_gate_change(
            target_gate, change_kind, details, str(candidate_row_id), operator,
            self._conn, self._writer, correlation_id=cid, now_millis=self._now_millis,
        )


__all__ = ["ConsoleEnactGateChange", "GateChangeNotApproved", "CandidateNotFound"]
