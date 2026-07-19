"""rev 0.4.14: the re-ask backstop detects answer-quoting confirmation rounds.

Three interviews on the deployed panel each ran exactly three rounds, rounds 2-3 re-asking
already-answered questions - citing the operator's answers verbatim as their divergence signals -
and the rev-0.3.86 Jaccard backstop never fired (its signal-field anchor now carries the freshest
text every round; its min-questions gate exempted round 2 entirely). The corpus below is a
SYNTHETIC reconstruction of that shape - two anonymized interviews (rounds + answers) whose
rounds 2-3 quote a verbatim run from a prior answer, plus a non-overlapping control. It preserves
the property the detector was measured against (a shared 5-word shingle between a prior answer and
a later round's divergence question+signal); the real operator corpus is not shipped (it stays in
the private repo's history).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.roles.research import ResearchRole

# --- synthetic corpus: two interviews, each round-1 genuine, rounds 2-3 quoting prior answers ---


def _payload(assumed_objective, divergence_points, signal_level="medium"):
    return json.dumps({
        "assumed_objective": assumed_objective,
        "divergence_points": divergence_points,
        "governing_preferences": [
            {"preference": "Keep the change to a single well-scoped feature.",
             "signal": "the request", "strength": "stated"},
            {"preference": "All existing tests must continue to pass.",
             "signal": "the request", "strength": "stated"},
        ],
        "memory_consulted": True,
        "signal_level": signal_level,
    })


# Interview 1 — a temperature-conversion subcommand. Rounds 266/269 quote answers 264/267.
ANSWERS = {
    "264": ("1. Round the converted value to two decimal places and never use scientific "
            "notation, so the output stays human readable for everyday temperatures.\n"
            "2. Accept the unit suffix in either case, treating c and C as celsius and f and F "
            "as fahrenheit, and reject any other suffix with a clear error."),
    "267": ("1. Apply the rounding after the conversion so the two decimal places reflect the "
            "final converted value. Nothing further, draft the spec."),
    # Interview 2 — a CSV column-selection subcommand. Rounds 304/307 quote answers 302/305.
    "302": ("1. When a requested column name does not exist, exit with a nonzero status and "
            "print the missing name to stderr, rather than silently skipping it.\n"
            "2. Preserve the original column order from the header row, not the order the "
            "columns were requested on the command line."),
    "305": ("1. Abort the whole run on the first missing column name. Nothing further, draft "
            "the spec."),
}

ROUNDS = {
    # Interview 1
    "263": _payload(  # round 1 — genuine
        "Add a temperature-conversion subcommand that converts between celsius and fahrenheit.",
        [{"question": "Should the value and unit be one argument or separate flags?",
          "signal": "The seed asks to convert temperatures but does not fix the input syntax."}]),
    "266": _payload(  # round 2 — QUOTES answer 264
        "Add a temperature-conversion subcommand, rounding the output.",
        [{"question": "Should the rounding apply before or after the unit conversion?",
          "signal": "The prior answer already states: round the converted value to two decimal "
                    "places and never use scientific notation, so the output stays human "
                    "readable for everyday temperatures."}], signal_level="medium"),
    "269": _payload(  # round 3 — QUOTES answers 264 and 267
        "Add a temperature-conversion subcommand with case-insensitive suffixes.",
        [{"question": "Confirm the suffix case handling?",
          "signal": "As already answered, accept the unit suffix in either case, treating c and "
                    "C as celsius and f and F as fahrenheit, and reject any other suffix with a "
                    "clear error."},
         {"question": "Confirm the rounding order?",
          "signal": "Per the prior reply, apply the rounding after the conversion so the two "
                    "decimal places reflect the final converted value."}], signal_level="high"),
    # Interview 2
    "301": _payload(  # round 1 — genuine (the cross-interview control)
        "Add a CSV column-selection subcommand that outputs only the requested columns.",
        [{"question": "Should columns be selected by header name, by numeric index, or both?",
          "signal": "The seed mentions choosing columns but does not say whether the selector "
                    "accepts header names or numeric positions."}]),
    "304": _payload(  # round 2 — QUOTES answer 302
        "Add a CSV column-selection subcommand with strict missing-column handling.",
        [{"question": "Should a missing column abort the whole run or skip that row?",
          "signal": "The clarification says when a requested column name does not exist, exit "
                    "with a nonzero status and print the missing name to stderr, rather than "
                    "silently skipping it."}], signal_level="medium"),
    "307": _payload(  # round 3 — QUOTES answers 302 and 305
        "Add a CSV column-selection subcommand preserving header order.",
        [{"question": "Confirm the output column ordering?",
          "signal": "As stated, preserve the original column order from the header row, not the "
                    "order the columns were requested on the command line."},
         {"question": "Confirm the abort behavior?",
          "signal": "Per the reply, abort the whole run on the first missing column name."}],
        signal_level="high"),
}


def _fires(q_seq, answer_seqs):
    return ResearchRole._answer_quote_reask(ROUNDS[q_seq], [ANSWERS[a] for a in answer_seqs])


def _shared_shingles(q_seq, answer_seqs, n=5):
    """Test-local margin counter, duplicating the production tokenizer over the corpus — the
    boolean alone would let a future tokenizer/scope tweak silently erode the margin to the
    n=6 zero-margin failure the setting was chosen to avoid (diff-review catch)."""
    import re

    def shingles(source):
        words = re.findall(r"[a-z0-9/=.\-]+", source.lower())
        return {" ".join(words[k:k + n]) for k in range(len(words) - n + 1)}

    payload = ROUNDS[q_seq]
    i, j = payload.find("{"), payload.rfind("}")
    divs = json.loads(payload[i:j + 1]).get("divergence_points") or []
    text = " ".join(f"{d.get('question', '')} {d.get('signal', '')}" for d in divs)
    return max(len(shingles(text) & shingles(ANSWERS[a])) for a in answer_seqs)


def test_all_four_guilty_rounds_fire_against_their_prior_answers():
    # interview 1's rounds 2-3 and interview 2's rounds 2-3, each vs the answers that preceded
    # them - each quotes a verbatim run from its prior answer, and the margin itself is pinned
    # >= 2 so erosion toward the zero-margin (n=6) failure cannot pass silently
    assert _fires("266", ["264"]) and _shared_shingles("266", ["264"]) >= 2
    assert _fires("269", ["264", "267"]) and _shared_shingles("269", ["264", "267"]) >= 2
    assert _fires("304", ["302"]) and _shared_shingles("304", ["302"]) >= 2
    assert _fires("307", ["302", "305"]) and _shared_shingles("307", ["302", "305"]) >= 2


def test_cross_interview_control_stays_quiet():
    # a genuinely-new first round vs the OTHER interview's answers shares nothing
    assert not _fires("301", ["264", "267"])


def test_short_answers_can_never_trigger():
    # an answer under n tokens has no shingles - a bare ack or the ans-{qid} fixture id (ONE
    # token under the hyphen-keeping tokenizer) is structurally unable to fire
    assert not ResearchRole._answer_quote_reask(ROUNDS["266"], ["ok"])
    assert not ResearchRole._answer_quote_reask(ROUNDS["266"], ["ans-corr-1-q0"])
    assert not ResearchRole._answer_quote_reask(ROUNDS["266"], [])


def test_end_to_end_quote_round_stops_the_interview():
    # round 1 valid, round 2 quotes round 1's answer in its divergence signal -> the interview
    # stops after ONE question (asked >= 1 gate - the min-questions floor no longer shields
    # round-2 duplicates) and the spec still drafts.
    import asyncio
    import sqlite3

    from devharness.events.bus import EventBus
    from devharness.mcp.parallax import ParallaxClient
    from devharness.migrate import migrate

    answer_text = "match error tokens on word boundaries so failed=0 never false-positives"
    round1 = json.dumps({"assumed_objective": "build X", "signal_level": "high",
                         "divergence_points": [{"question": "boundaries or substrings?",
                                                "signal": "the seed is ambiguous"}]})
    round2 = json.dumps({"assumed_objective": "build X", "signal_level": "high",
                         "divergence_points": [{"question": "confirm the matching rule?",
                                                "signal": f"the answer states: {answer_text}"}]})

    state = {"i": 0}

    async def query(*, prompt, options):
        class _R:
            total_cost_usd = 0.0
            usage = {}
            is_error = False
        r = _R()
        r.result = [round1, round2][min(state["i"], 1)]
        state["i"] += 1
        yield r

    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)

    def answer_fn(question_id, question_text):
        bus.emit_sync("question_answered", {"question_id": question_id, "answer_text": answer_text,
                      "correlation_id": "corr-q", "answered_at_millis": 1}, correlation_id="corr-q")
        return answer_text

    role = ResearchRole.spawn(conn=conn, correlation_id="corr-q",
                              parallax=ParallaxClient(query_fn=query), event_bus=bus,
                              answer_fn=answer_fn, max_questions=5, now_millis=lambda: 7)
    asyncio.run(role.run("build X", "corr-q"))
    types = [r[0] for r in conn.execute("SELECT event_type FROM events ORDER BY seq")]
    assert types.count("question_asked") == 1  # the quoting round was never asked
    assert "spec_drafted" in types


def test_confirmation_turn_survives_an_answer_echo():
    # the placement lock (plan-review catch F2): a no-divergence CONFIRMATION payload whose
    # assumed_objective folds in the operator's answer must still reach the confirmation turn -
    # the detector sits strictly below the _no_divergence branch and never sees it.
    import asyncio
    import sqlite3

    from devharness.events.bus import EventBus
    from devharness.mcp.parallax import ParallaxClient
    from devharness.migrate import migrate

    answer_text = "match error tokens on word boundaries so failed=0 never false-positives"
    round1 = json.dumps({"assumed_objective": "build X", "signal_level": "high",
                         "divergence_points": [{"question": "boundaries or substrings?",
                                                "signal": "the seed is ambiguous"}]})
    confirm = json.dumps({"assumed_objective": f"build X and {answer_text}",
                          "divergence_points": []})

    state = {"i": 0}

    async def query(*, prompt, options):
        class _R:
            total_cost_usd = 0.0
            usage = {}
            is_error = False
        r = _R()
        r.result = [round1, confirm][min(state["i"], 1)]
        state["i"] += 1
        yield r

    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)

    def answer_fn(question_id, question_text):
        bus.emit_sync("question_answered", {"question_id": question_id, "answer_text": answer_text,
                      "correlation_id": "corr-c", "answered_at_millis": 1}, correlation_id="corr-c")
        return answer_text

    role = ResearchRole.spawn(conn=conn, correlation_id="corr-c",
                              parallax=ParallaxClient(query_fn=query), event_bus=bus,
                              answer_fn=answer_fn, max_questions=5, now_millis=lambda: 7)
    asyncio.run(role.run("build X", "corr-c"))
    types = [r[0] for r in conn.execute("SELECT event_type FROM events ORDER BY seq")]
    assert types.count("question_asked") == 2  # round 1 AND the confirmation turn both asked
    assert "spec_drafted" in types


def test_resolved_round_block_names_every_point():
    # rev 0.4.28 (the charfreq drive): the context threaded only the FIRST divergence point per
    # round, so a later elicit legitimately re-asked a settled later point — every point must be
    # enumerated as RESOLVED, with the answer once per round
    import json as _json

    from devharness.roles.research import resolved_round_block

    q = _json.dumps({"assumed_objective": "build a CLI", "signal_level": "high",
                     "divergence_points": [
                         {"question": "What counts as a word?", "signal": "tokenizer"},
                         {"question": "What output format?", "signal": "contract"},
                         {"question": "How is non-UTF-8 handled?", "signal": "exit codes"}]})
    block = resolved_round_block(q, "1. lowercase 2. table 3. exit 4")
    # ASKED, not RESOLVED (review catch): one answer may not address every point of a round —
    # declaring unaddressed points settled would make them permanently un-askable
    assert "ASKED" in block and "do not re-ask anything this answer already settles" in block
    for point in ("What counts as a word?", "What output format?", "How is non-UTF-8 handled?"):
        assert point in block  # ALL points named, not just the first
    assert block.count("ANSWER:") == 1


def test_resolved_round_block_falls_back_on_unparseable_text():
    from devharness.roles.research import resolved_round_block

    block = resolved_round_block("not json at all", "an answer")
    assert block.startswith("Q: ") and "an answer" in block  # the prior one-point behavior


def test_resolved_round_block_answer_survives_multipoint_length():
    # rev 0.4.29 review: a 300-char ANSWER cap truncated the very answers that settle later points,
    # re-introducing the re-ask defect for verbose multi-point answers (the charfreq round-2 answer
    # exceeded 300 chars) — the cap must comfortably hold a point-by-point answer
    import json as _json

    from devharness.roles.research import resolved_round_block

    q = _json.dumps({"assumed_objective": "x", "signal_level": "high",
                     "divergence_points": [{"question": "a?"}, {"question": "b?"}, {"question": "c?"}]})
    answer = "1. " + "alpha " * 20 + "2. " + "beta " * 20 + "3. non-UTF-8 fails with exit 4 " + "gamma " * 20
    assert len(answer) > 300
    block = resolved_round_block(q, answer)
    assert "non-UTF-8 fails with exit 4" in block  # the later points' answers are IN the context


def test_resolved_round_block_caps_point_count():
    # server-controlled payloads must not balloon the context (the rev-0.3.78 class)
    import json as _json

    from devharness.roles.research import resolved_round_block

    q = _json.dumps({"assumed_objective": "x", "signal_level": "high",
                     "divergence_points": [{"question": f"point {i}?"} for i in range(20)]})
    block = resolved_round_block(q, "yes")
    assert block.count("- point") == 6  # _RESOLVED_MAX_POINTS
