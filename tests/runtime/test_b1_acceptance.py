"""B1.7 cut-line acceptance: the full read-only loop research -> sign -> plan ->
explore, end to end, with no write lock ever taken."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import msgspec

from devharness import boot
from devharness.artifacts.spec import Assumption, SpecArtifact
from devharness.cli.answer import answer_question
from devharness.cli.sign import sign_spec
from devharness.events.bus import EventBus, verify_chain
from devharness.explore.runner import run_and_emit
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.director import DirectorRole

CID = "corr-b1"


class _R:
    total_cost_usd = 0.0
    result = "ok"
    usage = {"input_tokens": 10, "output_tokens": 5}
    is_error = False


def _reasoning():
    async def query(*, prompt, options):
        yield _R()

    return MCPReasoningClient(query_fn=query)


def _build_repo(root: Path):
    (root / "pyproject.toml").write_text('[project]\nname="x"\ndependencies=["fastapi","pytest"]\n')
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("x = 1\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_x(): pass\n")


def test_b1_read_only_loop_end_to_end(tmp_path):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry=registry)

    def lock_unclaimed():
        # B2's developer-role single-writer lock must never be taken in the read-only loop
        return conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 0

    assert lock_unclaimed()

    # --- research: research_started, two Q/A cycles, one assumption, spec_drafted ---
    bus.emit_sync("research_started", {"research_id": CID, "topic": "ship a feature"}, correlation_id=CID)
    for i, (q, a) in enumerate([("scope?", "the whole repo"), ("non-goals?", "none")]):
        qid = f"{CID}-q{i}"
        bus.emit_sync("question_asked", {"research_id": CID, "question_id": qid, "question_text": q}, correlation_id=CID)
        answer_question(conn, bus, qid, a, now_millis=lambda: 100 + i)
    bus.emit_sync(
        "assumption_flagged",
        {"research_id": CID, "text": "single operator", "confidence": 0.9, "low_confidence_flag": False},
        correlation_id=CID,
    )
    assert lock_unclaimed()

    spec_id = "spec-b1"
    spec = SpecArtifact(
        problem="ship a feature", scope="read-only loop", non_goals=[], interfaces=[],
        success_criteria=["signed"], verification_plan="tests",
        assumptions=[Assumption(text="single operator", confidence=0.9, low_confidence_flag=False)],
        correlation_id=CID,
    )
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, created_at_millis, signed) "
        "VALUES (?, 'spec', 1, ?, ?, 111, 0)",
        (spec_id, json.dumps(msgspec.to_builtins(spec)), CID),
    )
    conn.commit()
    bus.emit_sync("spec_drafted", {"spec_id": spec_id, "title": "ship a feature"}, correlation_id=CID)
    assert lock_unclaimed()

    # --- sign: real CLI path ---
    sign_spec(conn, bus, spec_id, operator="operator", now_millis=lambda: 222)
    assert conn.execute("SELECT signed FROM artifacts WHERE artifact_id = ?", (spec_id,)).fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM events WHERE event_type = 'spec_signed'").fetchone()[0] == 1
    assert lock_unclaimed()

    # --- plan: real DirectorRole against the signed spec ---
    director = DirectorRole.spawn(conn=conn, correlation_id=CID, reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 333)
    plan_id = asyncio.run(director.run(spec_id, CID))
    assert plan_id is not None
    decision_kinds = {
        json.loads(p[0])["decision_kind"] for p in conn.execute("SELECT payload FROM events WHERE event_type = 'director_decision'")
    }
    assert {"fork", "sequencing"} <= decision_kinds
    assert conn.execute("SELECT count(*) FROM events WHERE event_type = 'plan_drafted'").fetchone()[0] == 1
    assert conn.execute("SELECT artifact_type FROM artifacts WHERE artifact_id = ?", (plan_id,)).fetchone()[0] == "plan"
    assert lock_unclaimed()

    # --- explore: real read-only module on a fixture repo ---
    _build_repo(tmp_path)
    explore_id = run_and_emit(str(tmp_path), CID, bus, conn)
    assert conn.execute("SELECT count(*) FROM events WHERE event_type = 'explore_pass_completed'").fetchone()[0] == 1
    assert conn.execute("SELECT artifact_type FROM artifacts WHERE artifact_id = ?", (explore_id,)).fetchone()[0] == "explore_pass"
    assert lock_unclaimed()

    # --- Inv 7 + Inv 9: valid hash chain, every event correlated ---
    total = conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert verify_chain(conn) == total
    assert all(row[0] for row in conn.execute("SELECT correlation_id FROM events"))

    # --- each B1 handler updated its projection ---
    assert conn.execute("SELECT count(*) FROM proj_questions WHERE answered = 1").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM proj_assumptions").fetchone()[0] == 1
    assert conn.execute("SELECT signed FROM proj_draft_spec WHERE spec_id = ?", (spec_id,)).fetchone()[0] == 1
    assert conn.execute("SELECT signed_by FROM proj_signed_spec WHERE spec_id = ?", (spec_id,)).fetchone()[0] == "operator"
    assert conn.execute("SELECT count(*) FROM proj_plan").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM proj_explore_summary").fetchone()[0] == 1

    # --- Inv 8: parity rebuild reproduces all projection state ---
    assert check_projection_rebuild_parity(conn, registry) is True

    # --- 24-name boot check passes ---
    assert boot.check_required_gates_registered() is True
    assert len(boot.registered_check_names()) == len(boot.REQUIRED_GATES)

    assert lock_unclaimed()
