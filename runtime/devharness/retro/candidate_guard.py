"""Terminal-path duplicate-candidate guard (§S7, rev 0.4.24).

The r1 drain proved the gap: 14 terminals sharing one correlation history produced 20 near-duplicate
pending antibodies for 2 real defect classes — each terminal re-derives the same defect, and the LLM
re-words ``signature_name``/``pattern_text`` every time, so exact-match dedup alone cannot work. And
``devharness.db`` accumulated 18 identical ``quarantine_blocked`` rows (16 operator-rejected). The
signal path got its own coarse guard at rev 0.3.92 (``signal_scheduler.py`` — pending per
target_gate; the two mechanisms are deliberate siblings and must evolve in tandem); this is the
terminal path's, wired in ``RetroEngine._emit_candidate`` when a ``conn`` is threaded (default None =
no dedup — the signal path and direct-call tests are untouched).

Per-SOURCE rules (each choice measured / review-checked; the post-implementation review moved
quarantine off the blanket any-state rule):

- **llm antibody** — suppressed when a queue row of ANY review_state matches exactly on
  ``(COALESCE(signature_name,''), pattern_text)`` (the projection stores an empty signature_name as
  NULL), OR shares **>= 2** 5-word shingles with a prior **llm-sourced** row's ``pattern_text``.
  Threshold measured on the real r1 corpus: >= 1 wrongly suppresses one genuinely-different finding
  via quoted-operator-answer boilerplate; >= 2 gives zero wrong suppressions (20 -> 7). Any-state
  because LLM antibodies are re-derived LEARNINGS, not per-incident evidence: pending = dupe,
  approved = already learned, rejected = the operator already said no. The shingle pool is
  llm-sourced rows only — static-text rows are exact-matched, and cross-source shingle collisions
  (a superset quarantine pattern list sharing its leading shingles) were a review-confirmed
  over-suppression. Residual (documented): formulaic LLM phrasing could share >= 2 shingles with an
  old rejected row and suppress a genuinely new finding — measured 0 on r1; escape hatches: the
  ``candidates_suppressed_count`` on retro_run, the queryable queue, approve-by-row-id on any state.
- **t0 antibody** — any-state exact only. The per-terminal evidence survives regardless: every
  retro_run records ``t0_matched_signatures``, so a suppressed repeat is still attributable.
- **quarantine antibody** — **PENDING-only** exact, never shingle-matched (review catches: a
  multi-pattern list DOES form shingles, so a superset pattern combination — a genuinely different
  hostile record — would shingle-suppress; and any-state would make a post-review injection
  CAMPAIGN invisible — one rejected false positive would silence every later hostile terminal
  forever). Pending-only collapses the flood while one row awaits review; once reviewed, the next
  hostile terminal creates a fresh record with its own evidence_event_ids.
- **gate_change** — suppressed only while a PENDING row matches
  ``(target_gate, change_kind, signature_name)``, and only for a NON-empty signature_name.
  signature_name is load-bearing (four T0 signatures share ``("verifier_attached_gate",
  "tighten")``); an LLM gate proposal carries ``signature_name=""`` and is never deduped — two
  different empty-signature proposals on one gate+kind would collide on the empty key and the loser
  would be permanently lost (its terminal is consumed; review catch). Pending-only mirrors the
  rev-0.3.92 signal-guard semantics (a reviewed condition that persists creates a fresh candidate).

The shingle scan is O(llm queue rows) per candidate — fine at real store scale (dozens of rows); add
a recency bound if a store's queue ever grows past that.
"""

from devharness.textsim import word_shingles

_SHINGLE_THRESHOLD = 2  # measured on r1: >=1 over-suppresses via answer-quote boilerplate; >=2 clean


def is_duplicate_candidate(conn, kind: str, signature_name: str, template: dict, *, source: str = "llm") -> bool:
    """True when an about-to-be-emitted candidate duplicates an existing queue row (rules above)."""
    if kind == "antibody_candidate":
        pattern_text = template.get("pattern_text", "")
        if source == "quarantine":
            return conn.execute(
                "SELECT 1 FROM proj_antibody_queue "
                "WHERE COALESCE(signature_name, '') = ? AND pattern_text = ? AND review_state = 'pending' "
                "LIMIT 1",
                (signature_name or "", pattern_text),
            ).fetchone() is not None
        exact = conn.execute(
            "SELECT 1 FROM proj_antibody_queue "
            "WHERE COALESCE(signature_name, '') = ? AND pattern_text = ? LIMIT 1",
            (signature_name or "", pattern_text),
        ).fetchone()
        if exact is not None:
            return True
        if source == "llm":
            new = word_shingles(pattern_text)  # hoisted — one tokenization, intersected per row
            if new:
                for (prior_text,) in conn.execute(
                        "SELECT pattern_text FROM proj_antibody_queue WHERE source = 'llm'"):
                    if len(new & word_shingles(prior_text or "")) >= _SHINGLE_THRESHOLD:
                        return True
        return False
    if not signature_name:
        return False  # an LLM gate proposal ('' signature) is never deduped — distinct proposals collide
    row = conn.execute(
        "SELECT 1 FROM proj_gate_change_queue "
        "WHERE target_gate = ? AND change_kind = ? AND COALESCE(signature_name, '') = ? "
        "AND review_state = 'pending' LIMIT 1",
        (template.get("target_gate", ""), template.get("change_kind", "tighten"), signature_name),
    ).fetchone()
    return row is not None
