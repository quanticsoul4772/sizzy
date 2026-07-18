"""§S9 per-role spend telemetry (rev 0.3.56): cost_spent events feed proj_cost.

The proj_cost projection ("tile 7: per-role cost vs budget") was an unfed B0 placeholder — zero rows
in every store ever produced, while real spend accumulated only in role memory. cost_spent is emitted
at role run-end (developer/research/director/discovery) and at dispatch-loop end for the
verifier+reviewer parallax client; the handler accumulates per-role totals, replay-parity safe.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry


def _bus():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry), registry


def test_cost_spent_accumulates_per_role_and_replays():
    # payloads carry `model` since rev 0.4.2 — proj_cost stays MODEL-AGNOSTIC (role-keyed): two
    # models under one role accumulate into the same row, and replay parity holds.
    conn, bus, registry = _bus()
    bus.emit_sync("cost_spent", {"role": "developer", "amount_usd": 1.25, "model": "m-frontier",
                                 "task_id": "t0", "spent_at_millis": 1, "correlation_id": "c"}, "c")
    bus.emit_sync("cost_spent", {"role": "developer", "amount_usd": 0.75, "model": "m-advisory",
                                 "task_id": "t1", "spent_at_millis": 2, "correlation_id": "c"}, "c")
    bus.emit_sync("cost_spent", {"role": "verify_review", "amount_usd": 2.5, "model": "m-frontier",
                                 "task_id": "t0", "spent_at_millis": 3, "correlation_id": "c"}, "c")

    rows = dict(conn.execute("SELECT role, spent_usd FROM proj_cost"))
    assert rows == {"developer": 2.0, "verify_review": 2.5}
    # budget_usd stays NULL (per-role budgets retired at constitution v0.2.0) — 0 would read as "$0 budget"
    assert conn.execute("SELECT budget_usd FROM proj_cost WHERE role='developer'").fetchone()[0] is None
    # Invariant 8: DELETE+replay reproduces the accumulation exactly
    assert check_projection_rebuild_parity(conn, registry) is True


def test_role_run_end_emits_cost_when_the_session_spent():
    # DeveloperRole.run's finally emits the worker session's realized cost; a zero-cost (mocked) run
    # emits nothing — asserted via the console dispatch path, which also proves the dispatch loop's
    # verify_review emission stays silent for a zero-cost parallax stub.
    from devharness.console.app import ConsoleApp
    from devharness.roles.developer import DeveloperRole

    conn, bus, registry = _bus()

    class _CostlyWorker(DeveloperRole):
        async def _run_worker(self, *a, **kw):
            self.total_cost_usd += 0.42  # what a real SDK worker session reports via ResultMessage
            return await super()._run_worker(*a, **kw)

    # the cheapest full-fidelity probe: drive run() directly with the write_hook seam
    import asyncio
    from devharness.artifacts.plan import PlannedTask
    from devharness.lock.base import SingleWriterLock
    import tempfile, subprocess as sp, os

    with tempfile.TemporaryDirectory() as td:
        repo = os.path.join(td, "r")
        os.makedirs(repo)
        for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
                    ["git", "config", "user.name", "t"]):
            sp.run(["git", "-C", repo] + cmd[1:] if cmd[0] == "git" else cmd, cwd=None,
                   check=True, capture_output=True)
        open(os.path.join(repo, "a.py"), "w").write("x = 1\n")
        sp.run(["git", "-C", repo, "add", "-A"], check=True, capture_output=True)
        sp.run(["git", "-C", repo, "commit", "-q", "-m", "init"], check=True, capture_output=True)

        async def noop_query(*, prompt, options):
            if False:
                yield None

        task = PlannedTask(task_id="t9", task_class="feature", description="d",
                           scope_boundary=["a.py"], dependencies=[], correlation_id="c")
        role = _CostlyWorker(event_bus=bus, conn=conn, context={}, base_path=repo,
                             query_fn=noop_query, lock=SingleWriterLock(),
                             write_hook=lambda e, s, t: None)
        asyncio.run(role.run(task, "c"))

    events = list(conn.execute(
        "SELECT json_extract(payload,'$.role'), json_extract(payload,'$.amount_usd'), "
        "json_extract(payload,'$.task_id') FROM events WHERE event_type='cost_spent'"))
    assert events == [("developer", 0.42, "t9")]
    assert dict(conn.execute("SELECT role, spent_usd FROM proj_cost")) == {"developer": 0.42}


def test_zero_cost_run_emits_nothing():
    # mocked runs (every test stub reports total_cost_usd == 0) stay event-clean
    conn, bus, registry = _bus()
    n_before = conn.execute("SELECT COUNT(*) FROM events WHERE event_type='cost_spent'").fetchone()[0]
    assert n_before == 0  # trivially, but pins the invariant the whole suite relies on


def test_scope_widener_cost_sink_fires_only_when_the_session_spent():
    # rev 0.3.60 (SC-6): resolve_extra_scope hands its session's realized cost to cost_sink — the
    # driver's closure turns that into a task-scoped cost_spent. The widener was the last task-scoped
    # spender whose cost was silently discarded. Zero-cost sessions never call the sink.
    import asyncio

    from devharness.artifacts.plan import PlannedTask
    from devharness.roles.scope_resolver import resolve_extra_scope

    task = PlannedTask(task_id="t1", task_class="feature", description="d",
                       scope_boundary=["a.py"], dependencies=[], correlation_id="c")

    class _Result:
        total_cost_usd = 0.19
        result = "[]"

    async def q(*, prompt, options):
        yield _Result()

    seen = []
    asyncio.run(resolve_extra_scope(".", task, query_fn=q, cost_sink=seen.append))
    assert seen == [0.19]

    _Result.total_cost_usd = 0.0  # a zero-cost (mocked) session stays silent
    seen.clear()
    asyncio.run(resolve_extra_scope(".", task, query_fn=q, cost_sink=seen.append))
    assert seen == []


class _Client:
    """A parallax/MCP client stand-in: realized spend + the model that billed it (rev 0.4.2)."""

    def __init__(self, cost, model="m-x"):
        self.total_cost_usd = cost
        self.model = model


def test_emit_client_costs_one_emission_per_distinct_client_with_its_model():
    # rev 0.4.2: the verify_review SUM hid the T1-verifier/frontier-reviewer split — the helper
    # emits per DISTINCT client, each carrying ITS model; zero-cost clients and None stay silent.
    from devharness.console.developer import emit_client_costs

    conn, bus, registry = _bus()
    verifier = _Client(0.30, "m-advisory")
    reviewer = _Client(1.70, "m-frontier")
    zero = _Client(0.0, "m-advisory")
    emit_client_costs(bus, [verifier, reviewer, verifier, zero, None],
                      role="verify_review", correlation_id="c", task_id="t0")

    rows = list(conn.execute(
        "SELECT json_extract(payload,'$.role'), json_extract(payload,'$.model'), "
        "json_extract(payload,'$.amount_usd'), json_extract(payload,'$.task_id') "
        "FROM events WHERE event_type='cost_spent' ORDER BY seq"))
    assert rows == [("verify_review", "m-advisory", 0.3, "t0"),
                    ("verify_review", "m-frontier", 1.7, "t0")]
    # the injected-single-client test posture (one client serves both seats) -> ONE emission
    conn2, bus2, _ = _bus()
    both = _Client(0.37, "m-one")
    emit_client_costs(bus2, [both, both], role="verify_review", correlation_id="c")
    rows2 = list(conn2.execute(
        "SELECT json_extract(payload,'$.model'), json_extract(payload,'$.task_id') "
        "FROM events WHERE event_type='cost_spent'"))
    assert rows2 == [("m-one", None)]  # task_id omitted when not given


def test_cost_spent_without_model_still_projects():
    # back-compat: every pre-0.4.2 event lacks `model` — projection + replay stay intact.
    conn, bus, registry = _bus()
    bus.emit_sync("cost_spent", {"role": "developer", "amount_usd": 0.5, "task_id": "t0",
                                 "spent_at_millis": 1, "correlation_id": "c"}, "c")
    assert dict(conn.execute("SELECT role, spent_usd FROM proj_cost")) == {"developer": 0.5}
    assert check_projection_rebuild_parity(conn, registry) is True


def test_certify_action_bills_its_reviewer_client():
    # rev 0.4.2 (SC-6 hole): the standalone certify action's reviewer client spent real frontier
    # tokens with NO cost_spent emission — the dispatch loop's emission never fires on this path.
    # A stubbed zero-cost reviewer stays silent.
    # top-level import (pytest prepend mode puts tests/runtime on sys.path): the dotted
    # `tests.runtime.` form breaks under CI's bare `pytest tests/runtime` (no repo root on sys.path)
    # and would create a second module instance besides the one pytest collected.
    from test_console_review_integrate import (
        _FakeReviewer, _app, _seed_started, _seed_verifier_pass,
    )

    app = _app()
    _seed_started(app)
    _seed_verifier_pass(app)
    reviewer = _FakeReviewer(app.writer, certified=True)
    reviewer.parallax = _Client(2.10, "m-frontier")   # the client the certification billed
    assert app.review().certify("t-1", reviewer=reviewer) is True
    rows = list(app.conn.execute(
        "SELECT json_extract(payload,'$.role'), json_extract(payload,'$.model'), "
        "json_extract(payload,'$.amount_usd'), json_extract(payload,'$.task_id') "
        "FROM events WHERE event_type='cost_spent'"))
    assert rows == [("verify_review", "m-frontier", 2.1, "t-1")]

    app2 = _app()
    _seed_started(app2)
    _seed_verifier_pass(app2)
    app2.review().certify("t-1", reviewer=_FakeReviewer(app2.writer, certified=True))  # no client
    assert app2.conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type='cost_spent'").fetchone()[0] == 0
