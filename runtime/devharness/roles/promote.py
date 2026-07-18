"""Promote a chosen work-item candidate to a signed-pending SpecArtifact (issue-discovery, step D).

The operator's pick (a question_answered carrying a candidate_id) IS the intent — no interview. This drafts a
SpecArtifact from the candidate's description + the target repo's structural summary via the synthesis
functions (synthesis_prompt/parse_spec_body) — NOT ResearchRole.run(), which is built around the interview
loop. It persists the spec signed=0 and emits spec_drafted; the operator then signs it (cli/sign), and
run_director + run_developer build it (the A/B/C external-target path).

The operator's selection is recorded as the spec's (required, non-empty) assumption — that is the design
intent, at full confidence, since the operator explicitly chose it.
"""

import json
import time
from uuid import uuid4

import msgspec

from devharness.artifacts.spec import Assumption, SpecArtifact
from devharness.events.registry import SpecDrafted
from devharness.explore.runner import run as run_explore_pass
from devharness.roles.research import repo_structural_summary
from devharness.roles.synthesis import parse_spec_body, synthesis_prompt


def chosen_candidate(conn, correlation_id):
    """The candidate row the operator picked (the latest question_answered for the pick-question), or None."""
    chosen_id = None
    for (p,) in conn.execute("SELECT payload FROM events WHERE event_type='question_answered'"):
        rec = json.loads(p)
        if rec.get("question_id") == f"{correlation_id}-pick":
            chosen_id = rec.get("answer_text")
    if not chosen_id:
        return None
    row = conn.execute(
        "SELECT candidate_id, title, description, kind, scope_hint, target_repo FROM proj_work_item_queue "
        "WHERE candidate_id = ?", (chosen_id,),
    ).fetchone()
    if not row:
        return None
    return {"candidate_id": row[0], "title": row[1], "description": row[2], "kind": row[3],
            "scope_hint": json.loads(row[4] or "[]"), "target_repo": row[5]}


async def promote(conn, event_bus, correlation_id, *, parallax=None, now_millis=None) -> str:
    """Draft + persist a SpecArtifact (signed=0) for the operator-chosen candidate; emit spec_drafted; return
    the spec_id. Raises ValueError if no candidate was chosen."""
    cand = chosen_candidate(conn, correlation_id)
    if cand is None:
        raise ValueError(f"no chosen work-item candidate for {correlation_id!r} — present + select one first")
    summary = repo_structural_summary(run_explore_pass(cand["target_repo"], correlation_id))
    body = await _synthesize(parallax, cand["description"], summary)
    spec = _build_spec(cand, body, correlation_id)
    now = (now_millis or (lambda: int(time.time() * 1000)))()
    spec_id = uuid4().hex
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, correlation_id, "
        "created_at_millis, signed) VALUES (?, 'spec', ?, ?, ?, ?, 0)",
        (spec_id, spec.schema_version, json.dumps(msgspec.to_builtins(spec)), correlation_id, now),
    )
    conn.commit()
    event_bus.emit_sync(
        "spec_drafted", msgspec.to_builtins(SpecDrafted(spec_id=spec_id, title=cand["title"][:80])),
        correlation_id=correlation_id,
    )
    return spec_id


async def _synthesize(parallax, intent, summary):
    """Compose the spec body from the chosen intent + repo summary via parallax; None → templated fallback."""
    if parallax is None or not hasattr(parallax, "complete"):
        return None
    try:
        result = await parallax.complete(synthesis_prompt(intent, [], repo_summary=summary))
    except Exception:
        return None
    return parse_spec_body(result.output if result and not result.is_error else None)


def _operator_assumption(cand) -> Assumption:
    return Assumption(
        text=f"Operator selected this work item to build: {cand['title']} — {cand['description']}",
        confidence=1.0, low_confidence_flag=False,
    )


def _build_spec(cand, body, correlation_id) -> SpecArtifact:
    assumptions = [_operator_assumption(cand)]  # required non-empty; the pick is the intent, full confidence
    if body is not None:
        return SpecArtifact(
            problem=cand["description"], scope=body["scope"], non_goals=body["non_goals"],
            interfaces=body["interfaces"], success_criteria=body["success_criteria"],
            verification_plan=body["verification_plan"], assumptions=assumptions, correlation_id=correlation_id,
        )
    return SpecArtifact(
        problem=cand["description"], scope=f"Build the operator-selected work item: {cand['title']}.",
        non_goals=[], interfaces=[],
        success_criteria=[f"{cand['title']} is implemented, tested, and reviewer-certified"],
        verification_plan="declared verification + reviewer certification",
        assumptions=assumptions, correlation_id=correlation_id,
    )
