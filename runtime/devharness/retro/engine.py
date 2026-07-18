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
from devharness.retro.llm_residue import analyze_with_llm, quarantine_check
from devharness.retro.t0_matcher import match_signatures


class RetroEngine:
    def __init__(self, llm_fn=None):
        self._llm_fn = llm_fn  # injectable; None -> the residue layer yields no candidates

    def analyze(self, retro_context, event_bus, *, now_millis=None) -> RetroResult:
        at = (now_millis or (lambda: int(time.time() * 1000)))()
        cid = retro_context.correlation_id
        emitted = []
        matched_signatures = []
        llm_invoked = False

        t0_matches = match_signatures(retro_context)
        for m in t0_matches:
            matched_signatures.append(m.signature_name)
            emitted.append(self._emit_candidate(event_bus, m.candidate_kind, m.signature_name,
                                                 m.candidate_payload_template, m.evidence_event_ids, "t0", cid, at))

        if not t0_matches:
            is_hostile, patterns = quarantine_check(retro_context)
            if is_hostile:
                # record the hostile attempt as an antibody; do NOT route it to the LLM
                emitted.append(self._emit_candidate(
                    event_bus, "antibody_candidate", "quarantine_blocked",
                    {"pattern_text": f"quarantine_blocked: {patterns}"},
                    [ev.get("event_id", "") for ev in retro_context.preceding_events], "quarantine", cid, at))
            else:
                llm_invoked = True
                for c in analyze_with_llm(retro_context, self._llm_fn):
                    emitted.append(self._emit_candidate(
                        event_bus, c["kind"], c.get("signature_name", ""), c,
                        c.get("evidence_event_ids", []), "llm", cid, at))

        return RetroResult(
            candidates_emitted=emitted, summary=f"t0={len(t0_matches)} llm={llm_invoked}",
            t0_matched_signatures=matched_signatures, llm_invoked=llm_invoked,
            candidate_kinds=sorted({c.split(":")[0] for c in emitted}),
        )

    def _emit_candidate(self, event_bus, kind, signature_name, template, evidence_event_ids, source, cid, at) -> str:
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
