"""Operator-review pipeline for retro CANDIDATEs (B5.2/B5.4, §S7; blocking review per OQ-B5-2=A).

The programmatic boundary the CLI (`cli/retro.py`) + the B5.6 dashboard tile wire onto. A CANDIDATE
stays `pending` until the operator explicitly approves or rejects it (blocking; no auto-archive, no TTL).
The review transition is driven by the `candidate_reviewed` event (parity-safe); SC-2 (no auto-apply)
holds strictly — the only path from a CANDIDATE to an enacted change is through these approve_* APIs.
Text-only enforcement (Inv 11): only the antibody queue — structurally text-only — can be approved as
an antibody; a gate-change candidate cannot.
"""

import time

import msgspec

from devharness.events.registry import CandidateRejected, CandidateReviewed
from devharness.retro.antibody_library import add_antibody
from devharness.retro.enacted_gate_changes import enact_gate_change, is_enactable


class CandidateNotFound(LookupError):
    """The candidate row id is not in the expected queue."""


def _now(now_millis):
    return (now_millis or (lambda: int(time.time() * 1000)))()


def _emit_reviewed(event_bus, candidate_row_id, candidate_kind, review_state, reviewed_by, review_reason, cid, at):
    event_bus.emit_sync(
        "candidate_reviewed",
        msgspec.to_builtins(CandidateReviewed(
            candidate_row_id=candidate_row_id, candidate_kind=candidate_kind, review_state=review_state,
            reviewed_by=reviewed_by, review_reason=review_reason, reviewed_at_millis=at, correlation_id=cid)),
        correlation_id=cid,
    )


def approve_antibody_candidate(candidate_row_id, approved_by, conn, event_bus, *, now_millis=None) -> int:
    """Approve an antibody candidate → mark its queue row approved + publish it into the active library.

    Returns the new antibody_row_id. Refuses anything not in proj_antibody_queue (a gate-change candidate
    cannot be approved as an antibody — the antibody queue is structurally text-only, Inv 11)."""
    row = conn.execute(
        "SELECT pattern_text, retro_run_correlation_id FROM proj_antibody_queue WHERE antibody_row_id = ?",
        (candidate_row_id,),
    ).fetchone()
    if row is None:
        raise CandidateNotFound(f"no antibody candidate with row id {candidate_row_id}")
    pattern_text, cid = row
    if not pattern_text:
        raise ValueError("cannot approve an antibody candidate with empty pattern_text")
    cid = cid or "operator_review"
    at = _now(now_millis)
    # mark approved FIRST, then publish — so the queue row is 'approved' by the time antibody_added fires
    _emit_reviewed(event_bus, candidate_row_id, "antibody_candidate", "approved", approved_by, "", cid, at)
    return add_antibody(pattern_text, str(candidate_row_id), approved_by, conn, event_bus, correlation_id=cid, now_millis=lambda: at)


def approve_gate_change_candidate(candidate_row_id, approved_by, conn, event_bus, *, now_millis=None) -> int:
    """Approve a gate-change candidate → mark its queue row approved, and AUTO-ENACT it into the running
    gate config (proj_enacted_gate_changes) when the change is auto-applicable. Returns the enacted_row_id,
    or None when the change is approved-but-not-auto-enacted.

    Only an `is_enactable` change (today: `add_signature` — an additive screening pattern a gate consults
    live) is auto-enacted; that is the only path from 'approved' to in-effect, and a core-gate weakening can
    never be enacted (Inv 12, re-checked in enact_gate_change; such a candidate is also auto-rejected at
    creation). The deterministic spine's `tighten`/`loosen` signals have no auto-applicable parameter — they
    are approved as the operator's decision (the `candidate_reviewed` event) but the OPERATOR applies them;
    proj_enacted_gate_changes therefore holds only what is actually in effect, never an inert row."""
    row = conn.execute(
        "SELECT target_gate, change_kind, change_details_json, retro_run_correlation_id "
        "FROM proj_gate_change_queue WHERE gate_change_row_id = ?", (candidate_row_id,)).fetchone()
    if row is None:
        raise CandidateNotFound(f"no gate-change candidate with row id {candidate_row_id}")
    target_gate, change_kind, details_json, cid = row
    cid = cid or "operator_review"
    at = _now(now_millis)
    details = msgspec.json.decode(details_json) if details_json else {}
    # mark approved FIRST, then enact — so the queue row is 'approved' by the time gate_change_enacted fires
    _emit_reviewed(event_bus, candidate_row_id, "gate_change_candidate", "approved", approved_by, "", cid, at)
    if not is_enactable(target_gate, change_kind, details):
        return None  # approved as an operator decision; nothing auto-applicable to enact (advisory signal)
    return enact_gate_change(target_gate, change_kind, details, str(candidate_row_id), approved_by,
                             conn, event_bus, correlation_id=cid, now_millis=lambda: at)


def _reject(candidate_row_id, candidate_kind, rejected_by, reason, conn, event_bus, now_millis):
    if not reason:
        raise ValueError("reject requires a non-empty reason")
    table = "proj_antibody_queue" if candidate_kind == "antibody_candidate" else "proj_gate_change_queue"
    pk = "antibody_row_id" if candidate_kind == "antibody_candidate" else "gate_change_row_id"
    cid_row = conn.execute(f"SELECT retro_run_correlation_id FROM {table} WHERE {pk} = ?", (candidate_row_id,)).fetchone()
    if cid_row is None:
        raise CandidateNotFound(f"no {candidate_kind} with row id {candidate_row_id}")
    cid = cid_row[0] or "operator_review"
    at = _now(now_millis)
    # the review transition (candidate_reviewed drives review_state) + the candidate_rejected audit trail
    _emit_reviewed(event_bus, candidate_row_id, candidate_kind, "rejected", rejected_by, reason, cid, at)
    event_bus.emit_sync(
        "candidate_rejected",
        msgspec.to_builtins(CandidateRejected(
            candidate_row_id=candidate_row_id, candidate_kind=candidate_kind, rejected_by=rejected_by,
            reason=reason, rejected_at_millis=at, correlation_id=cid)),
        correlation_id=cid,
    )


def reject_antibody_candidate(candidate_row_id, rejected_by, reason, conn, event_bus, *, now_millis=None) -> None:
    _reject(candidate_row_id, "antibody_candidate", rejected_by, reason, conn, event_bus, now_millis)


def reject_gate_change_candidate(candidate_row_id, rejected_by, reason, conn, event_bus, *, now_millis=None) -> None:
    _reject(candidate_row_id, "gate_change_candidate", rejected_by, reason, conn, event_bus, now_millis)
