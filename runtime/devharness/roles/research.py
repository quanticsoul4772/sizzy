"""Research role — the front of the line (B1.2).

Turns a raw operator idea into a reviewed, self-contained spec artifact with the
operator. Read/research tools only (parallax + mcp-reasoning); zero write tools.
Interviews the operator one question at a time, surfaces assumptions, then drafts
a SpecArtifact (B1.1 schema) with the assumptions populated and persists it.

The Agent SDK is driven through the injected ParallaxClient; the operator answer
seam (`answer_fn`) defaults to polling the event log for a matching
question_answered (the `devharness answer` CLI writes it).
"""

import json
import re
import time
from uuid import uuid4

import msgspec

from devharness.artifacts.spec import Assumption, SpecArtifact
from devharness.call_class import classify
from devharness.events.registry import (
    AssumptionFlagged,
    QuestionAsked,
    ResearchStarted,
    SpecDrafted,
)
from devharness.explore.runner import run as run_explore_pass
from devharness.mcp.mcp_reasoning import MCP_REASONING_TOOLS
from devharness.mcp.parallax import PARALLAX_TOOLS
from devharness.roles.base import AgentRole
from devharness.roles.synthesis import parse_spec_body, synthesis_prompt
from devharness.textsim import word_shingles


def repo_structural_summary(artifact) -> str:
    """A compact, structure-only summary of an ExplorePassArtifact for grounding the spec (Gap C).
    Structure only — file tree, manifests/frameworks, test setup, CI — never file contents."""
    top = sorted({e.path for e in artifact.file_tree if e.depth == 1})
    manifests = [
        m.path + (f" ({m.manifest_kind}" + (f"; frameworks: {', '.join(m.detected_frameworks)}" if m.detected_frameworks else "") + ")")
        for m in artifact.dependency_manifests
    ]
    tests = [f"{t.path} [{t.test_framework}]" for t in artifact.test_signatures]
    ci = [f"{c.path} [{c.ci_kind}]" for c in artifact.ci_configs]
    return "\n".join([
        f"Top-level entries: {', '.join(top) or '(none)'}",
        f"Dependency manifests: {'; '.join(manifests) or '(none)'}",
        f"Test setup: {'; '.join(tests) or '(none)'}",
        f"CI: {'; '.join(ci) or '(none)'}",
    ])

# Server tool catalogs the research role's inventory derives from.
SERVER_TOOL_CATALOG = {
    "parallax": PARALLAX_TOOLS,
    "mcp-reasoning": MCP_REASONING_TOOLS,
}


def tool_inventory_for(servers) -> list[str]:
    """All non-write (non-mutation) MCP tools from the allowed servers."""
    inventory = []
    for server in servers:
        for tool in SERVER_TOOL_CATALOG.get(server, []):
            full = f"mcp__{server}__{tool}"
            if classify(full) != "mutation":  # drop write-tagged tools (e.g. save/forget)
                inventory.append(full)
    return inventory


# Provenance markers in an elicit payload that mean an item came from parallax's GLOBAL,
# cross-project memory store rather than this operator's request. The harness never writes parallax
# memory (no save/recall/forget in runtime/; save/forget are dropped from the research inventory —
# test_research_role.py), so every stored/revealed item elicit surfaces is foreign to this run. If
# any future role gains parallax `save` authority, this blanket strip must be revisited.
_FOREIGN_SIGNAL_MARKERS = ("stored", "memory", "revealed")

# A new divergence whose salient tokens overlap an already-answered one by at least this Jaccard is
# treated as a re-ask (rev 0.3.86): elicit re-surfacing a resolved point despite the threaded Q&A.
_REASK_JACCARD = 0.5

# The operator confirming the scope confirmation turn with no correction (rev 0.3.68) — these answers
# add no scope note; anything else is captured as design intent for synthesis.
_CONFIRM_ACKS = frozenset({"ok", "okay", "yes", "y", "confirm", "confirmed", "good", "looks good",
                           "lgtm", "fine", "proceed", "go", "sounds good", "correct"})


# resolved_round_block bounds (rev 0.4.29 review): the ANSWER cap must comfortably hold a
# multi-point operator answer — a 300-char cap truncated the very answers that settle later points,
# re-introducing the re-ask defect for verbose answers (the charfreq round-2 answer exceeded 300).
# Points are capped in NUMBER too (the payload is server-controlled; unbounded enumeration would
# regrow the context-balloon class rev 0.3.78 bounded).
_RESOLVED_POINT_CAP = 300     # chars per enumerated question
_RESOLVED_ANSWER_CAP = 1000   # chars per round's answer
_RESOLVED_MAX_POINTS = 6      # points enumerated per round


def resolved_round_block(question_text: str, answer: str) -> str:
    """One interview round rendered as an explicit ASKED/ANSWER block for elicit's context threading.

    rev 0.4.28 (the charfreq drive's finding): the context previously threaded each round as
    ``readable_question_text`` — the FIRST divergence point only — so a multi-point round's later
    points were never named, and the next elicit round legitimately re-asked one (the judge cannot
    honor "never re-ask" for a point the context never told it was asked). Every point's question is
    enumerated, with the operator's answer once per round. Two review-shaped choices: the block says
    ASKED, not RESOLVED — one answer may not address every point of a round, and declaring
    unaddressed points settled would make them permanently un-askable (the judge decides coverage
    from the answer text; a genuine gap may still get a sharper follow-up); and each point carries
    up to 300 chars (a 150-char cut left long questions' substance out of the block, so a rephrase
    of the cut tail could not be matched to the entry). Parse failure falls back to the one-point
    summary (the prior behavior; ``_elicit_payload`` is the single payload parser)."""
    payload = ResearchRole._elicit_payload(question_text)
    points = [str(d["question"])[:_RESOLVED_POINT_CAP]
              for d in ((payload or {}).get("divergence_points") or [])[:_RESOLVED_MAX_POINTS]
              if isinstance(d, dict) and d.get("question")]
    if not points:
        return f"Q: {readable_question_text(question_text)} A: {answer[:_RESOLVED_ANSWER_CAP]}"
    lines = ["ASKED (the operator's answer follows — do not re-ask anything this answer already "
             "settles, in any wording or paraphrase):"]
    lines += [f"- {p}" for p in points]
    lines.append(f"ANSWER: {answer[:_RESOLVED_ANSWER_CAP]}")
    return "\n".join(lines)


def readable_question_text(question_text: str, *, max_len: int = 200) -> str:
    """A human-readable summary of an elicit payload — the first divergence point's question, or the
    assumed_objective, rather than the raw (possibly mid-object-truncated) JSON blob. Falls through to
    a plain slice on any parse failure or non-JSON text. Shared by ResearchRole's own round-to-round
    context threading and the operator console's question display (console/tui.py)."""
    i, j = question_text.find("{"), question_text.rfind("}")
    if i != -1 and j > i:
        try:
            obj = json.loads(question_text[i:j + 1])
            if isinstance(obj, dict):
                divs = obj.get("divergence_points") or []
                if divs and isinstance(divs[0], dict) and divs[0].get("question"):
                    return str(divs[0]["question"])[:max_len]
                if obj.get("assumed_objective"):
                    return str(obj["assumed_objective"])[:max_len]
        except Exception:
            pass
    return question_text[:max_len]


def full_question_text(question_text: str) -> str:
    """The COMPLETE question in readable form — every divergence point, never a summary.

    rev 0.4.12: a divergence round's ``question_text`` is the raw elicit JSON payload. The panel
    card rendered it verbatim (rev 0.4.10 traded the 400-char summary for a machine-JSON wall —
    live on a deployed-panel drive) and the TUI answer prompt showed only the FIRST question of
    four. Payload-less text (confirmation turns, discovery prose, operator passthrough) passes
    through byte-identical — the gate is the emitter's own ``ResearchRole._elicit_payload``, so
    formatter and interview loop agree by construction. Composed in ``_confirmation_question``'s
    plain-text style; ``signal_level``/``memory_consulted`` omitted (machine noise); no
    truncation. Defensive throughout — this runs on the panel's ``/state`` hot path, where a
    raise would kill the whole Drive pane, so any failure returns the input unchanged."""
    payload = ResearchRole._elicit_payload(question_text)
    if payload is None:
        return question_text
    try:
        lines = []
        objective = str(payload.get("assumed_objective") or "").strip()
        if objective:
            lines.append(objective)
        points = payload.get("divergence_points")
        if not isinstance(points, list):
            points = []  # {"divergence_points": null} passes the key-presence gate
        entries = []
        for dp in points:
            if not isinstance(dp, dict):
                continue
            q = str(dp.get("question") or "").strip()
            if not q:
                continue  # a null/empty question must not render the literal None
            entries.append((q, str(dp.get("signal") or "").strip()))
        if entries:
            lines.append("")
            lines.append("Questions to resolve:")
            for n, (q, s) in enumerate(entries, 1):
                lines.append(f"{n}. {q}")
                if s:
                    lines.append(f"   signal: {s}")
        prefs = ResearchRole._governing_preferences(question_text)
        if prefs:
            lines.append("")
            lines.append("Assuming:")
            lines.extend(f"  - {p}" for p in prefs)
        rendered = "\n".join(lines).strip()
        return rendered if rendered else question_text
    except Exception:
        return question_text


class ResearchRole(AgentRole):
    # NOTE: the canonical server name is "mcp-reasoning" (hyphen) per B1.0; the
    # B1.2 prompt wrote "mcp_reasoning" — using the hyphen so scoping/catalogs work.
    ALLOWED_MCP_SERVERS = ["parallax", "mcp-reasoning"]

    def __init__(self, *, parallax, event_bus, conn, context, answer_fn=None, target_repo=None,
                 max_questions=5, min_questions=2, now_millis=None, poll_interval=0.05, poll_limit=600):
        self.parallax = parallax
        self.event_bus = event_bus
        self.conn = conn
        self.context = context  # harness-assembled (assemble_context)
        self._answer_fn = answer_fn or self._poll_answer
        # Gap C: when set, research reads this EXISTING repo's structure (read-only explore pass) and grounds
        # the synthesized spec body in it, so it proposes a feature that fits the codebase. None = greenfield.
        self.target_repo = target_repo
        self._repo_summary = None
        self.max_questions = max_questions
        self.min_questions = min_questions
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))
        self.poll_interval = poll_interval
        self.poll_limit = poll_limit
        self.progress = 0  # C10: tool-call count
        self._assumptions: list[Assumption] = []

    @property
    def allowed_mcp_servers(self) -> list[str]:
        return list(self.ALLOWED_MCP_SERVERS)

    @property
    def tool_inventory(self) -> list[str]:
        return tool_inventory_for(self.ALLOWED_MCP_SERVERS)

    @classmethod
    def assemble_context(cls, conn, correlation_id) -> dict:
        """Harness builds the role's initial context from the event log + artifacts."""
        events = conn.execute(
            "SELECT event_type FROM events WHERE correlation_id = ? ORDER BY seq", (correlation_id,)
        ).fetchall()
        artifacts = conn.execute(
            "SELECT artifact_id FROM artifacts WHERE correlation_id = ?", (correlation_id,)
        ).fetchall()
        return {
            "correlation_id": correlation_id,
            "prior_events": [row[0] for row in events],
            "prior_artifacts": [row[0] for row in artifacts],
        }

    @classmethod
    def spawn(cls, *, conn, correlation_id, parallax, event_bus, **kwargs):
        """Construct the role with context assembled by the harness (never raw)."""
        context = cls.assemble_context(conn, correlation_id)
        return cls(parallax=parallax, event_bus=event_bus, conn=conn, context=context, **kwargs)

    # --- orchestration ---

    async def run(self, operator_idea: str, correlation_id: str) -> str:
        research_id = correlation_id
        self._emit("research_started", ResearchStarted(research_id=research_id, topic=operator_idea[:120]), correlation_id)

        # Gap C: ground the spec in an EXISTING target repo's structure (read-only explore pass) so the
        # feature research proposes fits the codebase, not just the seed. Structure only (no file contents).
        if self.target_repo:
            artifact = run_explore_pass(self.target_repo, correlation_id)
            self._repo_summary = repo_structural_summary(artifact)

        asked = 0
        qa_history: list[str] = []  # prior rounds' Q/A, threaded back into elicit's context so a later
        # round doesn't resurface the same divergence point the operator already resolved.
        answered_tokens: list = []  # salient token sets of answered divergences — the deterministic
        # re-ask backstop (rev 0.3.86) for when elicit ignores the context threading above.
        answered_answers: list[str] = []  # the operator's answers verbatim — the answer-quote
        # backstop's comparison corpus (rev 0.4.14).
        retried_structural = False  # rev 0.4.11: one payload-shape retry per interview — a retry
        # consumed early means a later transient ends the interview, which is safe (the spec still
        # drafts; the operator gates scope at sign-off) and avoids retry storms against a
        # persistently-failing server.
        broke_structural = False  # rev 0.4.11: the interview ended on a shapeless result — the
        # diverge fallback below must not run (its output comes from the same failing client).
        while asked < self.max_questions:
            context = "\n".join(qa_history) if qa_history else None
            question = await self.parallax.elicit(task=operator_idea, context=context)
            self.progress += 1
            # rev 0.3.76: an errored elicit (parallax server-side failure — e.g. its preference-array
            # inference returned misaligned counts) carries the raw MCP error text in .output. Without
            # this guard the loop below treated that error as a divergence question and emitted it as a
            # question_asked — surfacing "MCP error -32603 …" to the operator AS an interview question,
            # and answering it just re-hit the erroring call. Stop eliciting and synthesize from the
            # rounds gathered so far; the operator still shapes scope at the sign-off gate, and
            # _synthesize_body degrades to the template if its own parallax call errors too. Mirrors the
            # is_error check the synthesis path already has.
            if getattr(question, "is_error", False):
                break
            # elicit consults parallax's global, unscoped memory; strip any cross-project memory
            # item it surfaced before it reaches the operator or drives _no_divergence. Same variable
            # so the cleaned text governs the emitted question and the assumption.
            question_text = self._strip_foreign_memory(self._text(question.output))
            # rev 0.4.11: a tool error the SDK WORKER narrates as prose arrives with is_error=False —
            # the SESSION succeeded, the tool inside it failed — so the guard above never fires, and
            # the narration ("The elicit tool call returned an error … MCP error -32603 …") fell
            # through _no_divergence's parse-failure path into question_asked, reaching the operator's
            # question card VERBATIM (live: the first drive on the deployed panel, drive #3).
            # A valid elicit result IS an elicit-shaped JSON payload (the server contract always
            # serializes divergence_points); text carrying none — or an empty result, the same
            # stochastic failure class — is an errored round, decided by payload SHAPE, never by
            # keyword-scanning worker prose (the refuted heuristic class). Retry once per interview
            # (parallax failures are stochastic; the recorded convention is retry), then stop and
            # synthesize like the is_error path: worker prose can never become a question.
            if not question_text or self._elicit_payload(question_text) is None:
                if not retried_structural:
                    retried_structural = True
                    continue
                broke_structural = True
                break
            # Ask the operator ONLY when elicit reports a real ambiguity (non-empty
            # divergence_points). An unambiguous objective has nothing to resolve, so asking —
            # even once — only re-distills the same understanding and bills an SDK call; record
            # the objective and stop. The operator still controls scope at the spec sign-off gate.
            if self._no_divergence(question_text):
                # rev 0.3.68: a well-specified seed makes elicit report no divergence, which silently
                # skipped the WHOLE interview — the operator's pre-spec scope-shaping seat vanished
                # ("I never get interviewed anymore", reported live). Present exactly ONE confirmation
                # turn: surface the assumed objective + the stated governing_preferences for the operator
                # to confirm or correct, thread their answer into synthesis, then stop. Not the old
                # fixed-N re-distillation (the 328e2ab concern) — one confirmation, then synthesize.
                objective = self._assumed_objective(question_text) or question_text[:200]
                confirm_text = self._confirmation_question(objective, question_text)
                question_id = f"{research_id}-q{asked}"
                self._emit("question_asked", QuestionAsked(
                    research_id=research_id, question_id=question_id, question_text=confirm_text), correlation_id)
                answer = self._answer_fn(question_id, confirm_text)
                self._flag_assumption(research_id, correlation_id, text=objective,
                                      confidence=0.7, low_confidence_flag=False)
                if answer and answer.strip().lower() not in _CONFIRM_ACKS:
                    # the operator corrected or added scope — capture it as design intent for synthesis
                    self._flag_assumption(research_id, correlation_id,
                                          text=f"operator scope note: {answer}", confidence=0.6,
                                          low_confidence_flag=True)
                break
            # rev 0.3.78: once the minimum is met, stop when parallax reports the remaining ambiguity
            # is LOW signal — a diminishing-returns exit. Live, a bugfix drive drew SIX near-adjacent
            # scoping questions on a settled one-clause fix, and the growing elicit context tipped
            # parallax's own inference into a validation error (rev 0.3.76 now degrades that, but the
            # over-interviewing wasted operator time + spend). The operator still shapes scope at
            # sign-off; the max_questions cap is the hard backstop when parallax never reports low.
            if asked >= self.min_questions and self._low_signal(question_text):
                break
            # rev 0.3.86: deterministic re-ask backstop. Threading Q&A into elicit's context (above) is
            # meant to stop it resurfacing a resolved divergence, but elicit does not honor it reliably —
            # live it re-asked the same 'collapse repeated hyphens' point 3× (reworded), looping the
            # operator + billing each round. If this round's point overlaps an answered one, elicit has
            # nothing new → stop. Gated on the min floor (the quote detector below, rev 0.4.14, may end
            # an interview earlier — after a single answered question — so the floor is no longer hard).
            if asked >= self.min_questions and self._is_reask(question_text, answered_tokens):
                break
            # rev 0.4.14: answer-quote backstop. Live, three deployed-panel interviews each ran three
            # rounds with rounds 2–3 quoting the operator's PRIOR ANSWERS back as their divergence
            # signals — and the Jaccard above never fired: the signal field (its supposed stable
            # anchor) now carries the freshest text in the round, and the min-floor gate exempted
            # round 2 entirely. A round that quotes an answer verbatim is never a first real question,
            # so this runs from asked >= 1 and cannot starve the interview. MUST stay below the
            # _no_divergence confirmation branch: a confirmation payload's assumed_objective may
            # legitimately fold in the operator's answer, and firing there would kill the
            # confirmation turn (the rev-0.3.68 regression).
            if asked >= 1 and self._answer_quote_reask(question_text, answered_answers):
                break
            question_id = f"{research_id}-q{asked}"
            self._emit("question_asked", QuestionAsked(research_id=research_id, question_id=question_id, question_text=question_text), correlation_id)
            answer = self._answer_fn(question_id, question_text)
            # Preserve the operator's answer in full; only the (large, JSON) question
            # blob is bounded, so a long elicit payload can never truncate the answer.
            self._flag_assumption(research_id, correlation_id, text=f"{question_text[:100]} -> {answer}", confidence=0.6, low_confidence_flag=True)
            # rev 0.4.28: thread EVERY divergence point as resolved, not just the first — a later
            # round re-asked a settled point the one-point summary had silently dropped (charfreq)
            qa_history.append(resolved_round_block(question_text, answer))
            answered_tokens.append(self._salient_tokens(question_text))
            answered_answers.append(answer)
            asked += 1

        if not self._assumptions:
            if broke_structural:
                # rev 0.4.11 (plan-review blocker): the interview just broke on shapeless output
                # from this client — diverge would call the SAME failing client, and its guard
                # checks only is_error, so the SAME narration would land in an assumption and the
                # synthesis prompt one call later. Neutral placeholder directly instead.
                self._flag_assumption(research_id, correlation_id, text="needs operator review",
                                      confidence=0.5, low_confidence_flag=True)
            else:
                diverged = await self.parallax.diverge(problem=operator_idea)
                self.progress += 1
                # rev 0.3.76: don't fold an errored diverge's raw MCP-error output into an assumption
                # (same class as the elicit guard above); fall back to the neutral placeholder.
                div_text = "" if getattr(diverged, "is_error", False) else self._text(diverged.output)
                self._flag_assumption(research_id, correlation_id, text=(div_text or "needs operator review")[:200], confidence=0.5, low_confidence_flag=True)

        body = await self._synthesize_body(operator_idea)
        artifact_id = self._draft_and_persist(operator_idea, correlation_id, research_id, body=body)
        self._emit("spec_drafted", SpecDrafted(spec_id=artifact_id, title=operator_idea[:80]), correlation_id)
        # §S9 per-role spend (rev 0.3.56): the interview + synthesis client's realized cost for this
        # run. The client is normally fresh per run (console action / driver process); a reused client
        # would report a cumulative figure — acceptable for an advisory telemetry event.
        spent = float(getattr(self.parallax, "total_cost_usd", 0) or 0)
        if spent > 0:
            self.event_bus.emit_sync(
                "cost_spent",
                {"role": "research", "amount_usd": spent,
                 "model": getattr(self.parallax, "model", "") or "",
                 "spent_at_millis": self._now_millis(), "correlation_id": correlation_id},
                correlation_id=correlation_id,
            )
        return artifact_id

    async def _synthesize_body(self, operator_idea):
        """Compose the spec body (scope/non-goals/interfaces/success-criteria/verification-plan) from
        the interview via parallax (#2b). Returns the validated body dict, or None to fall back to the
        templated body — so a malformed model response never produces a worse spec than the template."""
        if not hasattr(self.parallax, "complete"):
            return None
        try:
            result = await self.parallax.complete(
                synthesis_prompt(operator_idea, [a.text for a in self._assumptions], repo_summary=self._repo_summary)
            )
        except Exception:
            return None
        # #M8: an errored CallResult carries no usable output — fall back to the template, don't parse it
        return parse_spec_body(result.output if result and not result.is_error else None)

    # --- helpers ---

    @staticmethod
    def _text(output) -> str:
        return output.strip() if isinstance(output, str) else str(output or "")

    @staticmethod
    def _elicit_payload(question_text: str):
        """The parsed elicit JSON payload, or None when the text carries none (rev 0.4.11).

        The server contract (mcp-parallax ``ElicitResult``) ALWAYS serializes
        ``divergence_points`` — key PRESENCE is the test, never truthiness: the legitimate
        no-divergence shape is ``{"divergence_points": []}``, and an or-of-gets would false-fire
        on it, silently killing the confirmation turn (plan-review catch). Requiring this one key
        (not or-``assumed_objective``) also shrinks the false-negative surface where a worker
        narration echoing field names inside a JSON fragment could slip past."""
        i, j = question_text.find("{"), question_text.rfind("}")
        if i == -1 or j <= i:
            return None
        try:
            obj = json.loads(question_text[i:j + 1])
        except Exception:
            return None
        if isinstance(obj, dict) and "divergence_points" in obj:
            return obj
        return None

    @staticmethod
    def _no_divergence(question_text: str) -> bool:
        """True when parallax's elicit payload reports no remaining divergence points.

        The payload is JSON (sometimes fenced); locate the outermost object and read
        divergence_points. On any parse failure, return False (keep interviewing)."""
        i, j = question_text.find("{"), question_text.rfind("}")
        if i == -1 or j <= i:
            return False
        try:
            obj = json.loads(question_text[i:j + 1])
        except Exception:
            return False
        return isinstance(obj, dict) and obj.get("divergence_points") == []

    @staticmethod
    def _low_signal(question_text: str) -> bool:
        """True when an elicit payload self-reports ``signal_level`` == "low" — parallax's own
        diminishing-returns signal that the remaining divergences aren't worth resolving. Any parse
        failure / missing field returns False (keep interviewing up to the cap), so this only ever
        stops EARLIER, never later, and only on an explicit low signal (rev 0.3.78)."""
        i, j = question_text.find("{"), question_text.rfind("}")
        if i == -1 or j <= i:
            return False
        try:
            obj = json.loads(question_text[i:j + 1])
        except Exception:
            return False
        return isinstance(obj, dict) and str(obj.get("signal_level", "")).lower() == "low"

    @staticmethod
    def _salient_tokens(question_text: str) -> frozenset:
        """The salient word set of an elicit payload's first divergence point — its ``question`` PLUS
        its ``signal`` (which references the same spec clauses across re-wordings, so it is the stabler
        anchor for detecting a reworded re-ask). Lowercased word tokens of length ≥ 4 (drops articles /
        short glue). Falls back to the whole text's tokens on a parse miss (rev 0.3.86)."""
        text = question_text
        i, j = question_text.find("{"), question_text.rfind("}")
        if i != -1 and j > i:
            try:
                divs = (json.loads(question_text[i:j + 1]) or {}).get("divergence_points") or []
                if divs and isinstance(divs[0], dict):
                    text = f"{divs[0].get('question', '')} {divs[0].get('signal', '')}"
            except (ValueError, TypeError):
                pass
        return frozenset(w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4)

    def _is_reask(self, question_text: str, answered: list) -> bool:
        """True when this round's divergence substantially overlaps one the operator already answered
        this run — a deterministic backstop for elicit re-surfacing a resolved point (it does NOT honor
        the threaded Q&A reliably; live it re-asked the same 'collapse repeated hyphens' point 3×,
        reworded each time, so an exact match misses it). Jaccard over the salient tokens; a slightly
        early stop is bounded by the min_questions floor + the operator's sign-off gate (rev 0.3.86)."""
        new = self._salient_tokens(question_text)
        if not new:
            return False
        for prev in answered:
            union = new | prev
            if union and len(new & prev) / len(union) >= _REASK_JACCARD:
                return True
        return False

    @staticmethod
    def _answer_quote_reask(question_text: str, prior_answers: list, n: int = 5) -> bool:
        """True when this round quotes a prior operator answer verbatim — a confirmation re-ask.

        rev 0.4.14: three deployed-panel interviews each re-asked answered questions in rounds
        2–3, citing the operator's answers as their divergence SIGNALS, and the Jaccard backstop
        never fired (the signal field it anchors on now carries the freshest text every round —
        measured 0.222 on rounds with identical first questions). The stable invariant of those
        rounds is the verbatim quote: any shared n-word shingle between a prior answer and this
        round's divergence question+signal text (parse-miss → full text, the _salient_tokens
        fallback pattern; the divergence scope excludes assumed_objective/governing_preferences,
        which elicit legitimately updates from the threaded Q&A). n=5, threshold ≥1 is the
        measured setting against the live corpus: 4/4 guilty rounds fire at margins 2/18/3/13,
        the cross-interview control stays quiet; n=6 left the two weakest rounds at exactly one
        shingle. An answer under n tokens (a bare ``ok``) has no shingles and can never trigger.
        The tokenizer keeps ``/=.-`` inside tokens, so paths/pins stay single tokens."""
        i, j = question_text.find("{"), question_text.rfind("}")
        text = question_text
        if i != -1 and j > i:
            try:
                divs = (json.loads(question_text[i:j + 1]) or {}).get("divergence_points") or []
                # scope to dict entries only when at least one exists — a degenerate all-non-dict
                # list keeps the full-text fallback (parity with _salient_tokens; review catch)
                if isinstance(divs, list) and any(isinstance(d, dict) for d in divs):
                    text = " ".join(
                        f"{d.get('question', '')} {d.get('signal', '')}"
                        for d in divs if isinstance(d, dict)
                    )
            except (ValueError, TypeError):
                pass

        # rev 0.4.24: the shingle math lives in textsim.word_shingles (extracted verbatim so the §S7
        # duplicate-candidate guard shares it); behavior here is unchanged.
        new = word_shingles(text, n)
        if not new:
            return False
        return any(new & word_shingles(str(a), n) for a in prior_answers)

    @staticmethod
    def _governing_preferences(question_text: str) -> list[str]:
        """The STATED governing_preferences from an elicit payload (the silent assumptions elicit
        made) — the ones worth confirming. Revealed/inferred provenance is dropped (revealed can be
        cross-project memory, handled by _strip_foreign_memory; inferred is a guess, not a stated
        constraint). Empty list on any parse failure."""
        i, j = question_text.find("{"), question_text.rfind("}")
        if i == -1 or j <= i:
            return []
        try:
            obj = json.loads(question_text[i:j + 1])
        except Exception:
            return []
        prefs = obj.get("governing_preferences") if isinstance(obj, dict) else None
        if not isinstance(prefs, list):
            return []
        return [str(p.get("preference", "")).strip() for p in prefs
                if isinstance(p, dict) and str(p.get("strength", "")).lower() == "stated"
                and str(p.get("preference", "")).strip()]

    def _confirmation_question(self, objective: str, question_text: str) -> str:
        """A single plain-text confirmation turn for the no-divergence case: what will be built and the
        assumptions it rests on, so the operator can confirm or correct BEFORE synthesis. Plain text (not
        JSON) so the console renders it verbatim (readable_question_text falls through to the literal)."""
        lines = [f"Confirm scope before I draft the spec — I will build: {objective}"]
        prefs = self._governing_preferences(question_text)
        if prefs:
            lines.append("Assuming:")
            lines += [f"  - {p}" for p in prefs]
        lines.append("Reply 'ok' to proceed, or add / correct anything.")
        return "\n".join(lines)

    @staticmethod
    def _assumed_objective(question_text: str):
        """Extract ``assumed_objective`` from an elicit JSON payload (None on parse failure)."""
        i, j = question_text.find("{"), question_text.rfind("}")
        if i == -1 or j <= i:
            return None
        try:
            obj = json.loads(question_text[i:j + 1])
        except Exception:
            return None
        return obj.get("assumed_objective") if isinstance(obj, dict) else None


    @staticmethod
    def _strip_foreign_memory(question_text: str) -> str:
        """Remove cross-project memory items from an elicit payload before it reaches the operator.

        elicit consults parallax's GLOBAL memory store, which the caller cannot scope, so a lesson
        from unrelated work can surface as a divergence_point / governing_preference (e.g. a Rust
        rmcp lesson matched on the word "router"). Drop those: governing_preferences with
        strength=='revealed' (the authoritative provenance field — a missing/other strength is kept),
        and divergence_points whose freeform signal names a memory source. divergence_points stay a
        LIST (possibly []) so _no_divergence's `== []` early-stop keeps working. Any parse failure or
        a brace-free string returns the input UNCHANGED — only ever an improvement, never worse."""
        i, j = question_text.find("{"), question_text.rfind("}")
        if i == -1 or j <= i:
            return question_text
        try:
            obj = json.loads(question_text[i:j + 1])
        except Exception:
            return question_text
        if not isinstance(obj, dict):
            return question_text
        prefs = obj.get("governing_preferences")
        if isinstance(prefs, list):
            obj["governing_preferences"] = [
                p for p in prefs
                if not (isinstance(p, dict) and str(p.get("strength", "")).lower() == "revealed")
            ]
        divs = obj.get("divergence_points")
        if isinstance(divs, list):
            obj["divergence_points"] = [
                d for d in divs
                if not (isinstance(d, dict)
                        and any(m in str(d.get("signal", "")).lower() for m in _FOREIGN_SIGNAL_MARKERS))
            ]
        return json.dumps(obj)

    def _emit(self, event_type, struct, correlation_id) -> None:
        self.event_bus.emit_sync(event_type, msgspec.to_builtins(struct), correlation_id=correlation_id)

    def _flag_assumption(self, research_id, correlation_id, *, text, confidence, low_confidence_flag) -> None:
        self._assumptions.append(Assumption(text=text, confidence=confidence, low_confidence_flag=low_confidence_flag))
        self._emit(
            "assumption_flagged",
            AssumptionFlagged(research_id=research_id, text=text, confidence=confidence, low_confidence_flag=low_confidence_flag),
            correlation_id,
        )

    def _poll_answer(self, question_id, question_text) -> str:
        """Default operator-answer seam: poll the event log for question_answered."""
        for _ in range(self.poll_limit):
            for (payload,) in self.conn.execute(
                "SELECT payload FROM events WHERE event_type = 'question_answered'"
            ):
                record = json.loads(payload)
                if record.get("question_id") == question_id:
                    return record.get("answer_text", "")
            time.sleep(self.poll_interval)
        raise TimeoutError(f"no question_answered for {question_id}")

    def _draft_and_persist(self, operator_idea, correlation_id, research_id, body=None) -> str:
        if body is not None:  # #2a: research-synthesized spec body from the interview
            spec = SpecArtifact(
                problem=operator_idea,
                scope=body["scope"],
                non_goals=body["non_goals"],
                interfaces=body["interfaces"],
                success_criteria=body["success_criteria"],
                verification_plan=body["verification_plan"],
                assumptions=self._assumptions,
                correlation_id=correlation_id,
            )
        else:  # fallback: templated body (the prior behaviour)
            spec = SpecArtifact(
                problem=operator_idea,
                scope=f"research-derived scope for {research_id}",
                non_goals=[],
                interfaces=[],
                success_criteria=["spec signed by the operator"],
                verification_plan="declared verification + reviewer certification",
                assumptions=self._assumptions,
                correlation_id=correlation_id,
            )
        artifact_id = uuid4().hex
        self.conn.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
            "correlation_id, created_at_millis, signed) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (artifact_id, "spec", spec.schema_version, json.dumps(msgspec.to_builtins(spec)), correlation_id, self._now_millis()),
        )
        self.conn.commit()
        return artifact_id
