"""B1.2: ResearchRole orchestration (SDK mocked)."""
import json

import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.call_class import classify
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.mcp.parallax import ParallaxClient
from devharness.roles.research import ResearchRole, readable_question_text


class _R:
    def __init__(self, text, cost=0.0):
        self.total_cost_usd = cost
        self.result = text
        self.usage = {}
        self.is_error = False


def _query(text):
    async def query(*, prompt, options):
        yield _R(text)

    return query


def _query_seq(texts):
    """A query_fn that returns a different payload per call (clamped to the last) — for driving the
    interview loop with distinct per-round elicit responses."""
    state = {"i": 0}

    async def query(*, prompt, options):
        i = min(state["i"], len(texts) - 1)
        state["i"] += 1
        yield _R(texts[i])

    return query


def _divpayload(question, signal, level="high"):
    return json.dumps({"assumed_objective": "build X", "signal_level": level,
                       "divergence_points": [{"question": question, "signal": signal}]})


def _answer_fn(bus, correlation_id):
    def answer(question_id, question_text):
        bus.emit_sync(
            "question_answered",
            {"question_id": question_id, "answer_text": f"ans-{question_id}", "correlation_id": correlation_id, "answered_at_millis": 1},
            correlation_id=correlation_id,
        )
        return f"ans-{question_id}"

    return answer


def test_allowed_servers_and_no_write_tools():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    role = ResearchRole.spawn(
        conn=conn, correlation_id="corr-1", parallax=ParallaxClient(query_fn=_query("q?")), event_bus=EventBus(conn)
    )
    assert role.allowed_mcp_servers == ["parallax", "mcp-reasoning"]
    inv = role.tool_inventory
    assert "Edit" not in inv and "Write" not in inv and "Bash" not in inv
    assert all(classify(tool) != "mutation" for tool in inv)  # no write-tagged MCP tools
    assert "mcp__parallax__save" not in inv  # mutation tool dropped
    assert "mcp__parallax__elicit" in inv


def test_run_emits_events_in_order():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    role = ResearchRole.spawn(
        conn=conn,
        correlation_id="corr-1",
        # rev 0.4.11: elicit results are payload-shaped per the server contract — bare prose is now
        # (correctly) an errored round, so this fixture carries the real shape.
        parallax=ParallaxClient(query_fn=_query(_divpayload("what is the scope?", "s1"))),
        event_bus=bus,
        answer_fn=_answer_fn(bus, "corr-1"),
        max_questions=1,
        now_millis=lambda: 7,
    )
    artifact_id = asyncio.run(role.run("build a thing", "corr-1"))

    order = [row[0] for row in conn.execute("SELECT event_type FROM events ORDER BY seq")]
    first = {t: order.index(t) for t in ("research_started", "question_asked", "assumption_flagged", "spec_drafted")}
    assert first["research_started"] < first["question_asked"] < first["assumption_flagged"] < first["spec_drafted"]

    # the drafted spec is persisted with non-empty assumptions
    row = conn.execute("SELECT artifact_type, signed FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
    assert row == ("spec", 0)


def test_no_divergence_still_asks_one_confirmation_turn():
    # rev 0.3.68: a no-divergence elicit used to SKIP the interview entirely (the operator reported
    # "I never get interviewed anymore"). It now presents exactly ONE confirmation turn surfacing the
    # assumed objective + stated preferences, then synthesizes.
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    payload = ('{"assumed_objective": "build X", "divergence_points": [], "governing_preferences": '
               '[{"preference": "stdlib only", "strength": "stated"}, '
               '{"preference": "a guessed thing", "strength": "inferred"}]}')
    role = ResearchRole.spawn(
        conn=conn, correlation_id="corr-2", parallax=ParallaxClient(query_fn=_query(payload)),
        event_bus=bus, answer_fn=_answer_fn(bus, "corr-2"), now_millis=lambda: 7,
    )
    artifact_id = asyncio.run(role.run("build X", "corr-2"))
    types = [row[0] for row in conn.execute("SELECT event_type FROM events ORDER BY seq")]
    assert types.count("question_asked") == 1  # exactly one confirmation turn, not zero, not N
    assert "spec_drafted" in types
    # the confirmation question surfaces the objective + the STATED preference (not the inferred one)
    q = conn.execute("SELECT json_extract(payload,'$.question_text') FROM events "
                     "WHERE event_type='question_asked'").fetchone()[0]
    assert "build X" in q and "stdlib only" in q and "a guessed thing" not in q
    assert row_type(conn, artifact_id) == "spec"


def test_no_divergence_confirmation_correction_becomes_a_scope_note():
    # if the operator answers with a correction (not a bare 'ok'), it is captured as a scope note
    # assumption for synthesis; a bare ack adds no extra assumption.
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)

    def answer_with_correction(question_id, question_text):
        bus.emit_sync("question_answered", {"question_id": question_id, "answer_text": "also support TOML",
                      "correlation_id": "corr-3", "answered_at_millis": 1}, correlation_id="corr-3")
        return "also support TOML"

    role = ResearchRole.spawn(
        conn=conn, correlation_id="corr-3",
        parallax=ParallaxClient(query_fn=_query('{"assumed_objective": "build X", "divergence_points": []}')),
        event_bus=bus, answer_fn=answer_with_correction, now_millis=lambda: 7,
    )
    asyncio.run(role.run("build X", "corr-3"))
    notes = [row[0] for row in conn.execute(
        "SELECT json_extract(payload,'$.text') FROM events WHERE event_type='assumption_flagged'")]
    assert any("operator scope note: also support TOML" in n for n in notes)


def test_errored_elicit_is_not_surfaced_as_a_question():
    # rev 0.3.76: a parallax elicit that returns is_error (a server-side failure — e.g. its
    # preference-array inference produced misaligned counts) carries the raw MCP error text in
    # .output. The loop used to emit that as a question_asked, showing the operator "MCP error
    # -32603 …" AS an interview question (live on a bugfix drive). It must instead stop eliciting
    # and synthesize from what it has — no question surfaced, a spec still drafted.
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)

    async def errq(*, prompt, options):
        r = _R("MCP error -32603: [validation_failure] preference arrays disagree: 6 texts, 5 signals")
        r.is_error = True
        yield r

    role = ResearchRole.spawn(
        conn=conn, correlation_id="corr-e",
        parallax=ParallaxClient(query_fn=errq), event_bus=bus,
        answer_fn=_answer_fn(bus, "corr-e"), max_questions=3, now_millis=lambda: 7,
    )
    artifact_id = asyncio.run(role.run("fix the decode crash", "corr-e"))
    types = [row[0] for row in conn.execute("SELECT event_type FROM events ORDER BY seq")]
    assert "question_asked" not in types  # the raw error was NOT surfaced to the operator
    assert "spec_drafted" in types        # the run still drafted a spec (synthesis degrades cleanly)
    assert row_type(conn, artifact_id) == "spec"
    # the errored diverge fallback used the neutral placeholder, not the raw error text
    notes = [row[0] for row in conn.execute(
        "SELECT json_extract(payload,'$.text') FROM events WHERE event_type='assumption_flagged'")]
    assert not any("MCP error" in (n or "") for n in notes)


_NARRATED_ERROR = ("The `elicit` tool call returned an error rather than a result:\n\n```\n"
                   "MCP error -32603: [validation_failure] validation failure: divergence arrays "
                   "disagree: 3 questions, 4 signals\n```\n\nThis is an internal validation failure "
                   "from the `parallax` server itself. Let me know if you'd like me to retry the call.")


def _run_role(query_fn, correlation_id, **kwargs):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    role = ResearchRole.spawn(
        conn=conn, correlation_id=correlation_id,
        parallax=ParallaxClient(query_fn=query_fn), event_bus=bus,
        answer_fn=_answer_fn(bus, correlation_id), now_millis=lambda: 7, **kwargs)
    artifact_id = asyncio.run(role.run("audit cron jobs by their logs", correlation_id))
    return conn, artifact_id


def test_worker_narrated_tool_error_is_not_surfaced_as_a_question():
    # rev 0.4.11: a tool error the SDK WORKER narrates as prose arrives with is_error=False (the
    # SESSION succeeded; the tool inside failed) — the 0.3.76 session-flag guard never fires. Live:
    # the deployed panel's first drive showed the narration verbatim on the operator's question card
    # (the deployed panel, drive #3). Both variants: brace-free prose, and prose whose embedded JSON
    # fragment parses to a dict WITHOUT divergence_points. Neither may become a question, land in
    # an assumption (the diverge fallback runs on the SAME failing client — the plan-review
    # blocker), and the spec must still draft.
    braced = 'Tool failed: {"code": -32603, "message": "divergence arrays disagree"} — retry?'
    for prose in (_NARRATED_ERROR, braced):
        conn, artifact_id = _run_role(_query(prose), "corr-n")
        types = [r[0] for r in conn.execute("SELECT event_type FROM events ORDER BY seq")]
        assert "question_asked" not in types
        assert "spec_drafted" in types
        notes = [r[0] for r in conn.execute(
            "SELECT json_extract(payload,'$.text') FROM events WHERE event_type='assumption_flagged'")]
        assert notes and not any("-32603" in (n or "") or "elicit" in (n or "") for n in notes)


def test_structural_failure_retries_once_then_recovers():
    # rev 0.4.11: parallax failures are stochastic — the first shapeless round is retried once;
    # a valid payload on the retry proceeds normally. max_questions=1 pins one question because
    # _query_seq clamps to its final payload (plan-review catch: an unpinned loop would ask the
    # clamped question a second time before the re-ask backstop fires).
    conn, _ = _run_role(
        _query_seq([_NARRATED_ERROR, _divpayload("streaming or whole-file?", "s1")]),
        "corr-r", max_questions=1)
    questions = [r[0] for r in conn.execute(
        "SELECT json_extract(payload,'$.question_text') FROM events WHERE event_type='question_asked'")]
    assert len(questions) == 1 and "streaming or whole-file?" in questions[0]
    assert conn.execute("SELECT COUNT(*) FROM events WHERE event_type='spec_drafted'").fetchone()[0] == 1


def test_pure_no_divergence_shape_still_reaches_the_confirmation_turn():
    # rev 0.4.11 key-presence semantics: {"divergence_points": []} WITHOUT assumed_objective is a
    # legitimate no-divergence payload — the gate must pass it through to the rev-0.3.68
    # confirmation turn, not treat it as an errored round (an or-of-gets would false-fire here).
    conn, _ = _run_role(_query('{"divergence_points": []}'), "corr-c")
    questions = [r[0] for r in conn.execute(
        "SELECT json_extract(payload,'$.question_text') FROM events WHERE event_type='question_asked'")]
    assert len(questions) == 1  # the confirmation turn, not a break
    assert conn.execute("SELECT COUNT(*) FROM events WHERE event_type='spec_drafted'").fetchone()[0] == 1


def test_low_signal_stops_the_interview_after_the_minimum():
    # rev 0.3.78: once min_questions is met, a low-signal elicit payload ends the interview
    # (diminishing returns) instead of grinding on up to the cap — the over-interviewing that tipped
    # parallax mid-session. Every elicit here reports a real divergence but signal_level "low".
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    payload = ('{"assumed_objective": "fix it", "divergence_points": [{"question": "edge case?"}], '
               '"signal_level": "low"}')
    role = ResearchRole.spawn(
        conn=conn, correlation_id="corr-ls",
        parallax=ParallaxClient(query_fn=_query(payload)), event_bus=bus,
        answer_fn=_answer_fn(bus, "corr-ls"), max_questions=5, min_questions=2, now_millis=lambda: 7,
    )
    asyncio.run(role.run("fix it", "corr-ls"))
    asked = [r[0] for r in conn.execute(
        "SELECT event_type FROM events WHERE event_type='question_asked'")]
    # exactly min_questions asked, then the low signal stopped it — not all 5
    assert len(asked) == 2


def test_high_signal_interviews_up_to_the_cap():
    # the backstop: when parallax never reports low signal, the max_questions cap bounds it (now 5).
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    # DISTINCT questions per round — a real high-signal interview asks something new each time (a fixed
    # identical payload would now correctly trip the rev-0.3.86 re-ask backstop and stop early).
    payloads = [_divpayload(f"alpha{i} bravo{i}", f"charlie{i} delta{i}") for i in range(5)]
    role = ResearchRole.spawn(
        conn=conn, correlation_id="corr-hs",
        parallax=ParallaxClient(query_fn=_query_seq(payloads)), event_bus=bus,
        answer_fn=_answer_fn(bus, "corr-hs"), max_questions=5, min_questions=2, now_millis=lambda: 7,
    )
    asyncio.run(role.run("build X", "corr-hs"))
    asked = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type='question_asked'").fetchone()[0]
    assert asked == 5  # capped, not unbounded


def test_reask_of_an_answered_divergence_stops_the_interview():
    # rev 0.3.86: elicit re-surfacing a resolved point (it re-asked the same 'collapse repeated hyphens'
    # divergence 3x live, REWORDED each time) must be caught by the deterministic Jaccard backstop —
    # keyed on the stabler 'signal' field — and stop, not loop the operator up to the cap.
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    same_signal = "the spec lists replace runs with single hyphen and collapse repeated hyphens as separate overlapping requirements"
    payloads = [
        _divpayload("should collapse repeated hyphens be a separate pass?", same_signal),      # q0
        _divpayload("which exit code applies on empty stdin input?",                            # q1 (distinct)
                    "the spec never states the process exit status for empty input"),
        _divpayload("should repeated hyphens use a distinct collapsing step instead?", same_signal),  # q2 = reworded q0
        _divpayload("does the tool also accept a file path argument?",                          # q3 (would-be, never reached)
                    "the spec mentions stdin and an argument but not files"),
    ]
    role = ResearchRole.spawn(
        conn=conn, correlation_id="corr-rk",
        parallax=ParallaxClient(query_fn=_query_seq(payloads)), event_bus=bus,
        answer_fn=_answer_fn(bus, "corr-rk"), max_questions=5, min_questions=2, now_millis=lambda: 7,
    )
    asyncio.run(role.run("build a slug tool", "corr-rk"))
    asked = [json.loads(p)["question_text"] for (p,) in conn.execute(
        "SELECT payload FROM events WHERE event_type='question_asked' ORDER BY seq")]
    # q0 + q1 asked; q2 (reworded q0) detected as a re-ask -> stop. NOT 5, and the reworded dup unasked.
    assert len(asked) == 2, asked
    assert all("distinct collapsing step" not in q for q in asked)


def row_type(conn, artifact_id):
    return conn.execute("SELECT artifact_type FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()[0]


def test_readable_question_text_extracts_the_divergence_point():
    payload = ('{"assumed_objective": "build a thing", '
               '"divergence_points": [{"question": "top 5 of what?"}]}')
    assert readable_question_text(payload) == "top 5 of what?"


def test_readable_question_text_falls_back_to_assumed_objective():
    payload = '{"assumed_objective": "build a thing", "divergence_points": []}'
    assert readable_question_text(payload) == "build a thing"


def test_readable_question_text_falls_back_on_non_json():
    assert readable_question_text("just plain text") == "just plain text"


def test_readable_question_text_respects_max_len():
    # the plain-slice fallback (non-JSON input) respects max_len
    assert len(readable_question_text("a" * 500, max_len=50)) == 50
    # the extracted divergence-point question is also capped at max_len
    payload = '{"divergence_points": [{"question": "%s"}]}' % ("b" * 500)
    assert len(readable_question_text(payload, max_len=50)) == 50


def test_full_question_text_renders_every_divergence_point_readably():
    # rev 0.4.12: the card rendered the raw elicit JSON (rev 0.4.10's full-text swap) and the TUI
    # prompt only the FIRST question — live, a four-question round. The full renderer
    # carries EVERY question + the objective + stated preferences, with no JSON syntax.
    from devharness.roles.research import full_question_text
    payload = json.dumps({
        "assumed_objective": "build a URL shortener",
        "divergence_points": [
            {"question": "coarse parsing ok?", "signal": "only four cases enumerated"},
            {"question": "stderr redirects monitored?", "signal": "cron errors flow via 2>&1"},
        ],
        "governing_preferences": [
            {"preference": "stdlib only", "strength": "stated"},
            {"preference": "a guessed thing", "strength": "inferred"},
        ],
        "signal_level": "medium", "memory_consulted": True,
    })
    out = full_question_text(payload)
    assert "build a URL shortener" in out
    assert "1. coarse parsing ok?" in out and "2. stderr redirects monitored?" in out
    assert "only four cases enumerated" in out
    assert "stdlib only" in out and "a guessed thing" not in out  # stated only, like the confirm turn
    assert "{" not in out and '"question"' not in out and "memory_consulted" not in out


def test_full_question_text_passes_prose_and_malformed_through_unchanged():
    from devharness.roles.research import full_question_text
    prose = "Confirm scope before I draft the spec — I will build: X\nAssuming:\n  - stdlib only"
    assert full_question_text(prose) == prose                      # confirmation turns untouched
    assert full_question_text("just plain text") == "just plain text"
    assert full_question_text('{"broken": ') == '{"broken": '      # malformed passthrough


def test_full_question_text_degrades_never_raises():
    # /state hot path: a raise kills the operator's whole Drive pane. Every admissible-but-hostile
    # shape degrades readable or passes through — and never renders the literal 'None'.
    from devharness.roles.research import full_question_text
    # non-list divergence container ({"divergence_points": null} passes the key-presence gate)
    out = full_question_text('{"assumed_objective": "o", "divergence_points": null}')
    assert "o" in out and "None" not in out
    # non-dict entry + null question are skipped, not rendered
    out = full_question_text(json.dumps({
        "assumed_objective": "o",
        "divergence_points": ["stray", {"question": None}, {"question": "real q?"}]}))
    assert "real q?" in out and "None" not in out and "stray" not in out
    # missing objective still renders the questions
    out = full_question_text('{"divergence_points": [{"question": "only q?"}]}')
    assert "only q?" in out
    # empty divergence (unreachable live — the confirmation turn takes it — kept as robustness)
    out = full_question_text('{"assumed_objective": "o", "divergence_points": []}')
    assert out.strip()
