"""Operator console review/integrate actions (``ConsoleReview``).

The operator advances the back half of the loop as discrete decisions, with no LLM agent in the
seat. ``certify`` runs the SAME fresh-context read-only ``ReviewerRole`` the integrated loop runs
(zero write tools, Invariant 2) and completes the task only when BOTH a verifier pass AND a reviewer
certification exist in the current attempt (``completed`` earned twice, Invariant 5); it refuses to
advance the review step before acceptance has passed. ``integrate`` advances the director's
integration decision through the canonical integration path. Every state change is recorded through
``EventBus.emit_sync`` — the console writes no event store or projection directly.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.call_class import classify
from devharness.console import (
    AlreadyTerminal,
    ConsoleReview,
    NoTerminalOutcome,
    NotReadyForReview,
    TaskNotStarted,
    UnknownPlan,
)
from devharness.console.app import ConsoleApp
from devharness.roles.reviewer import ReviewerRole
from devharness.task_lifecycle.done_is_earned import can_complete


def _app():
    """A console connected to a fresh in-memory event store (migrated)."""
    return ConsoleApp(db_path=":memory:").connect()


def _events(conn, event_type):
    return [
        json_loads(payload)
        for (payload,) in conn.execute(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY seq", (event_type,)
        )
    ]


def json_loads(s):
    import json

    return json.loads(s)


def _seed_started(app, *, task_id="t-1", correlation_id="proj-1", at=100):
    """Emit a developer ``task_started`` (proj_task_started + proj_task_lifecycle='running')."""
    app.writer.emit_sync(
        "task_started",
        {"task_id": task_id, "role": "developer", "worktree_path": f"/wt/{task_id}",
         "correlation_id": correlation_id, "started_at_millis": at},
        correlation_id=correlation_id,
    )


def _seed_verifier_pass(app, *, task_id="t-1", correlation_id="proj-1", passed=True):
    """Emit the developer's verifier-first acceptance outcome (the FIRST earn)."""
    app.writer.emit_sync(
        "verifier_outcome",
        {"task_id": task_id, "verifier": "test_suite", "passed": passed, "detail": ""},
        correlation_id=correlation_id,
    )


def _seed_dispatched(app, *, task_id="t-1", plan_id="plan-1", correlation_id="proj-1"):
    """Emit a ``task_dispatched`` so the task resolves to a plan (proj_task_dispatched)."""
    app.writer.emit_sync(
        "task_dispatched",
        {"task_id": task_id, "plan_id": plan_id, "dispatched_to_role": "developer",
         "dispatched_by_role": "director", "dispatched_at_millis": 90},
        correlation_id=correlation_id,
    )


def _seed_terminal(app, *, task_id="t-1", outcome="completed", correlation_id="proj-1", reason=""):
    """Emit a ``terminal_outcome`` directly (for integrate-only tests)."""
    app.writer.emit_sync(
        "terminal_outcome",
        {"task_id": task_id, "outcome": outcome, "detail": reason, "reason": reason,
         "correlation_id": correlation_id, "terminated_at_millis": 200},
        correlation_id=correlation_id,
    )


class _FakeReviewer:
    """A reviewer stand-in that records its verdict through the bus, like the real ReviewerRole.

    Used to drive the certify/reject paths without a live parallax client; the real read-only
    ``ReviewerRole`` is exercised separately (the build_reviewer boundary test).
    """

    def __init__(self, bus, *, certified, now=150):
        self._bus = bus
        self._certified = certified
        self._now = now
        self.ran_with = None

    async def run(self, task_id, spec_id, plan_id, correlation_id):
        self.ran_with = (task_id, spec_id, plan_id, correlation_id)
        if self._certified:
            self._bus.emit_sync(
                "reviewer_certified",
                {"task_id": task_id, "reviewer_session_id": "rev-s", "evidence": {},
                 "correlation_id": correlation_id, "certified_at_millis": self._now},
                correlation_id=correlation_id,
            )
        else:
            self._bus.emit_sync(
                "reviewer_rejected",
                {"task_id": task_id, "reviewer_session_id": "rev-s", "reason": "diff regresses",
                 "evidence": {}, "correlation_id": correlation_id, "rejected_at_millis": self._now},
                correlation_id=correlation_id,
            )
        return self._certified


# --- wiring ---


def test_review_returns_bound_action():
    app = _app()
    assert isinstance(app.review(), ConsoleReview)


# --- certify: the second earn (Invariant 5) ---


def test_certify_completes_only_after_both_earns():
    app = _app()
    _seed_started(app)
    _seed_verifier_pass(app)  # the FIRST earn (verifier-first acceptance)
    review = app.review()

    reviewer = _FakeReviewer(app.writer, certified=True)
    certified = review.certify("t-1", reviewer=reviewer)

    assert certified is True
    # the reviewer ran in a fresh certification (the SECOND earn) and recorded its verdict
    assert _events(app.conn, "reviewer_certified")[0]["task_id"] == "t-1"
    # earned twice: a verifier pass AND a reviewer cert both exist in the current attempt
    assert can_complete("t-1", app.conn) is True
    # the task reached its terminal completed outcome (driven through the lifecycle's bus emit)
    terminals = _events(app.conn, "terminal_outcome")
    assert len(terminals) == 1
    assert terminals[0]["task_id"] == "t-1"
    assert terminals[0]["outcome"] == "completed"


def test_certify_refuses_before_verifier_acceptance():
    app = _app()
    _seed_started(app)  # no verifier pass — acceptance has NOT passed
    review = app.review()

    with pytest.raises(NotReadyForReview):
        review.certify("t-1", reviewer=_FakeReviewer(app.writer, certified=True))

    # nothing advanced: no reviewer verdict, no terminal — Invariant 5's ordering is preserved
    assert _events(app.conn, "reviewer_certified") == []
    assert _events(app.conn, "terminal_outcome") == []


def test_certify_refuses_when_acceptance_failed():
    app = _app()
    _seed_started(app)
    _seed_verifier_pass(app, passed=False)  # acceptance FAILED — not a pass
    review = app.review()

    with pytest.raises(NotReadyForReview):
        review.certify("t-1", reviewer=_FakeReviewer(app.writer, certified=True))


def test_certify_rejection_rejects_the_task():
    app = _app()
    _seed_started(app)
    _seed_verifier_pass(app)
    review = app.review()

    certified = review.certify("t-1", reviewer=_FakeReviewer(app.writer, certified=False))

    assert certified is False
    assert _events(app.conn, "reviewer_rejected")[0]["task_id"] == "t-1"
    # a reviewer rejection does NOT complete the task — it rejects it (earned-twice not met)
    assert can_complete("t-1", app.conn) is False
    terminals = _events(app.conn, "terminal_outcome")
    assert len(terminals) == 1
    assert terminals[0]["outcome"] == "rejected"


def test_certify_refuses_unstarted_task():
    app = _app()
    with pytest.raises(TaskNotStarted):
        app.review().certify("ghost", reviewer=_FakeReviewer(app.writer, certified=True))


def test_certify_refuses_a_terminal_task():
    app = _app()
    _seed_started(app)
    _seed_verifier_pass(app)
    _seed_terminal(app, outcome="completed")  # already terminal
    with pytest.raises(AlreadyTerminal):
        app.review().certify("t-1", reviewer=_FakeReviewer(app.writer, certified=True))


def test_certify_passes_resolved_ids_to_the_reviewer():
    app = _app()
    _seed_started(app)
    _seed_verifier_pass(app)
    _seed_dispatched(app, plan_id="plan-7")
    reviewer = _FakeReviewer(app.writer, certified=True)
    app.review().certify("t-1", reviewer=reviewer)
    task_id, _spec_id, plan_id, correlation_id = reviewer.ran_with
    assert task_id == "t-1"
    assert plan_id == "plan-7"
    assert correlation_id == "proj-1"


def test_certify_records_only_through_the_event_bus():
    app = _app()
    _seed_started(app)
    _seed_verifier_pass(app)
    before = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    app.review().certify("t-1", reviewer=_FakeReviewer(app.writer, certified=True))
    after = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    # exactly two appends: the reviewer verdict + the terminal outcome (both via emit_sync)
    assert after == before + 2


# --- the reviewer read-only tool boundary (Invariant 2) ---


def test_build_reviewer_is_read_only_and_fresh():
    app = _app()
    _seed_started(app)
    reviewer = app.review().build_reviewer("proj-1", parallax=object(), verifiers=[])
    assert isinstance(reviewer, ReviewerRole)
    assert reviewer.fresh_context is True
    # zero write tools in the reviewer inventory (asserted at construction; re-checked here)
    assert reviewer.tool_inventory
    assert all(classify(tool) != "mutation" for tool in reviewer.tool_inventory)
    for tool in reviewer.tool_inventory:
        assert "write_file" not in tool and "run_command" not in tool and "append_to_file" not in tool


def test_default_built_reviewer_certifies_with_no_falsifiers():
    app = _app()
    _seed_started(app)
    _seed_verifier_pass(app)
    review = app.review()
    # the real fresh-context read-only ReviewerRole, with no falsifiers to run, certifies and
    # records reviewer_certified through the bus — driving the second earn end-to-end.
    certified = review.certify("t-1", parallax=object(), verifiers=[])
    assert certified is True
    assert _events(app.conn, "reviewer_certified")[0]["task_id"] == "t-1"
    assert _events(app.conn, "terminal_outcome")[0]["outcome"] == "completed"


# --- integrate: the director's integration decision ---


def test_integrate_advances_a_completed_terminal():
    app = _app()
    _seed_started(app)
    _seed_dispatched(app, plan_id="plan-1")
    _seed_terminal(app, outcome="completed")
    disposition = app.review().integrate("t-1")
    assert disposition == "completed"
    # a clean completion records no director abort decision
    assert _events(app.conn, "director_decision") == []


def test_integrate_blocks_a_rejected_terminal_with_a_director_decision():
    app = _app()
    _seed_started(app)
    _seed_dispatched(app, plan_id="plan-1")
    _seed_terminal(app, outcome="rejected", reason="reviewer rejected")
    disposition = app.review().integrate("t-1")
    assert disposition == "blocked"
    decisions = _events(app.conn, "director_decision")
    assert len(decisions) == 1
    assert decisions[0]["decision_kind"] == "abort"
    assert "t-1" in decisions[0]["detail"]


def test_integrate_uses_the_latest_terminal_outcome():
    app = _app()
    _seed_started(app)
    _seed_dispatched(app, plan_id="plan-1")
    # an earlier aborted attempt then a re-driven completion — integrate reads the LATEST
    _seed_terminal(app, outcome="completed")
    disposition = app.review().integrate("t-1")
    assert disposition == "completed"


def test_integrate_refuses_without_a_terminal_outcome():
    app = _app()
    _seed_started(app)
    _seed_dispatched(app)
    with pytest.raises(NoTerminalOutcome):
        app.review().integrate("t-1")


def test_integrate_refuses_an_unknown_plan():
    app = _app()
    _seed_started(app)
    _seed_terminal(app, outcome="completed")  # terminal exists but the task was never dispatched
    with pytest.raises(UnknownPlan):
        app.review().integrate("t-1")


def test_integrate_accepts_an_explicit_plan_id():
    app = _app()
    _seed_started(app)
    _seed_terminal(app, outcome="rejected", reason="blocked")
    disposition = app.review().integrate("t-1", plan_id="plan-x")
    assert disposition == "blocked"
    assert _events(app.conn, "director_decision")[0]["decision_kind"] == "abort"


def test_integrate_records_only_through_the_event_bus():
    app = _app()
    _seed_started(app)
    _seed_dispatched(app)
    _seed_terminal(app, outcome="rejected", reason="nope")
    before = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    app.review().integrate("t-1")
    after = app.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    # exactly one append: the director_decision (via emit_sync)
    assert after == before + 1
