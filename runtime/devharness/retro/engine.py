"""Compositional retro engine (B5.1, §S7; OQ-B5-4=C).

analyze() runs the T0 pattern-matcher first; matched signatures emit deterministic CANDIDATEs with no
LLM call. The unmatched residue is quarantined (§S7) and, only if clean, routed to the LLM for novel
patterns. CANDIDATEs land in the two operator-review queues (antibody / gate-change) and never
auto-apply (SC-2). Returns a RetroResult the scheduler folds into the retro_run event.
"""

import time

import msgspec

from devharness.events.registry import AntibodyCandidate, GateChangeCandidate
from devharness.retro.base import RetroResult
from devharness.retro.candidate_guard import is_duplicate_candidate
from devharness.retro.llm_residue import analyze_with_llm, quarantine_check
from devharness.retro.t0_matcher import match_signatures


class RetroEngine:
    def __init__(self, llm_fn=None):
        self._llm_fn = llm_fn  # injectable; None -> the residue layer yields no candidates

    def analyze(self, retro_context, event_bus, *, now_millis=None, conn=None) -> RetroResult:
        """``conn`` (rev 0.4.24, additive): when given, each candidate is checked against the queues
        via the duplicate-candidate guard before emitting — a duplicate is suppressed (counted in
        ``candidates_suppressed_count``, no event). Default ``None`` = no dedup, the prior behavior —
        the signal path deliberately does not thread it (its own rev-0.3.92 guard covers it)."""
        at = (now_millis or (lambda: int(time.time() * 1000)))()
        cid = retro_context.correlation_id
        emitted = []
        suppressed = 0
        matched_signatures = []
        llm_invoked = False

        def emit(kind, signature_name, template, evidence_event_ids, source):
            nonlocal suppressed
            r = self._emit_candidate(event_bus, kind, signature_name, template,
                                     evidence_event_ids, source, cid, at, conn=conn)
            if r is None:  # suppressed — never append (candidate_kinds splits each entry)
                suppressed += 1
            else:
                emitted.append(r)

        t0_matches = match_signatures(retro_context)
        for m in t0_matches:
            matched_signatures.append(m.signature_name)
            emit(m.candidate_kind, m.signature_name, m.candidate_payload_template, m.evidence_event_ids, "t0")

        if not t0_matches:
            is_hostile, patterns = quarantine_check(retro_context)
            if is_hostile:
                # record the hostile attempt as an antibody; do NOT route it to the LLM
                emit("antibody_candidate", "quarantine_blocked",
                     {"pattern_text": f"quarantine_blocked: {patterns}"},
                     [ev.get("event_id", "") for ev in retro_context.preceding_events], "quarantine")
            else:
                llm_invoked = True
                for c in analyze_with_llm(retro_context, self._llm_fn):
                    emit(c["kind"], c.get("signature_name", ""), c, c.get("evidence_event_ids", []), "llm")

        return RetroResult(
            candidates_emitted=emitted, summary=f"t0={len(t0_matches)} llm={llm_invoked}",
            t0_matched_signatures=matched_signatures, llm_invoked=llm_invoked,
            candidate_kinds=sorted({c.split(":")[0] for c in emitted}),
            candidates_suppressed_count=suppressed,
        )

    def _emit_candidate(self, event_bus, kind, signature_name, template, evidence_event_ids, source, cid, at,
                        *, conn=None) -> str | None:
        # rev 0.4.24: pre-emit dedup (handlers run synchronously inside emit_sync, so a prior emit in
        # this same analyze call is already visible — within-run dupes are caught too). Rules are
        # per-source (llm/t0/quarantine differ — see candidate_guard's docstring).
        if conn is not None and is_duplicate_candidate(conn, kind, signature_name, template, source=source):
            return None
        if kind == "antibody_candidate":
            struct = AntibodyCandidate(
                retro_run_correlation_id=cid, signature_name=signature_name,
                pattern_text=template.get("pattern_text", ""), evidence_event_ids=list(evidence_event_ids),
                source=source, created_at_millis=at, correlation_id=cid)
        else:
            struct = GateChangeCandidate(
                retro_run_correlation_id=cid, signature_name=signature_name,
                target_gate=template.get("target_gate", ""), change_kind=template.get("change_kind", "tighten"),
                change_details=template.get("change_details", {}), evidence_event_ids=list(evidence_event_ids),
                source=source, created_at_millis=at, correlation_id=cid)
        event_bus.emit_sync(kind, msgspec.to_builtins(struct), correlation_id=cid)
        return f"{kind}:{signature_name}"

    # the candidate kinds this run produced, for the retro_run event's candidate_kinds field
    def candidate_kinds_of(self, result: RetroResult) -> list:
        return sorted({c.split(":")[0] for c in result.candidates_emitted})
