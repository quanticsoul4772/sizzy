"""Operator console TUI: the live state panel reflects loop_state, action errors are
surfaced (never crash the app), list actions run on an empty store, and a down sidecar
falls back to polling without hanging. Async via Textual's headless run_test() pilot."""

import asyncio
import concurrent.futures
import json
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

pytest.importorskip("textual")  # the optional [tui] extra; skip cleanly if absent

from devharness.console.app import ConsoleApp  # noqa: E402
from devharness.console.tui import ConsoleTUI, _ProxyBus  # noqa: E402


def _app():
    return ConsoleApp(db_path=":memory:").connect()


class _EmptyConsumer:
    """A no-op SSE consumer: yields nothing, so the follower thread exits cleanly."""

    def frames(self):
        return iter(())


class _RaisingConsumer:
    """A down-sidecar consumer: raises like a refused connection."""

    def frames(self):
        raise ConnectionRefusedError("no sidecar")


class _NFrameConsumer:
    """Yields ``n`` dummy frames then ends — exercises the per-frame marshal."""

    def __init__(self, n: int = 2) -> None:
        self._n = n

    def frames(self):
        for _ in range(self._n):
            yield object()


def _seed_spec_artifact(conn, spec_id):
    """Insert an unsigned spec artifact the way the research role's storage does."""
    payload = {
        "problem": "p", "scope": "s", "non_goals": [], "interfaces": ["x"],
        "success_criteria": ["c"], "verification_plan": "v",
        "assumptions": [{"text": "a", "confidence": 0.9, "low_confidence_flag": False}],
        "correlation_id": "proj-1",
    }
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, ?, ?, ?, 0)",
        (spec_id, json.dumps(payload), "proj-1", 100),
    )
    conn.commit()


def _events(conn, event_type):
    return [
        json.loads(p)
        for (p,) in conn.execute(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY seq", (event_type,)
        )
    ]


async def test_state_panel_reflects_loop_state():
    app = _app()
    bus = app.writer
    bus.emit_sync("role_transitioned", {"to_role": "director"}, "c1")
    bus.emit_sync("spec_signed", {"spec_id": "spec-7", "signer": "operator", "signed_at_millis": 100}, "c1")
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        from textual.widgets import Static
        text = str(tui.query_one("#state", Static).render())
    assert "director" in text
    assert "signed spec-7 by operator" in text


async def test_begin_end_emit_role_transitioned_for_the_dashboard_tile():
    # rev 0.3.79: nothing else emits role_transitioned, so proj_role_state (the dashboard's
    # 'Active role' tile) was always empty. _begin/_end now feed it at the step boundaries.
    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        # a build step needs a file-backed DB; force _busy=None first, then drive _begin directly
        tui._console._db_path = "not-memory.db"  # bypass the :memory: build-step guard for _begin
        assert tui._begin("developer dispatch") is True
        tui._end()
    trans = [json.loads(p) for (p,) in app.conn.execute(
        "SELECT payload FROM events WHERE event_type='role_transitioned' ORDER BY seq")]
    assert [t["to_role"] for t in trans] == ["developer", "idle"]
    assert trans[0]["from_role"] == "idle" and trans[1]["from_role"] == "developer"
    # the projection reflects the latest transition
    assert app.conn.execute("SELECT role FROM proj_role_state WHERE id=1").fetchone()[0] == "idle"


async def test_cost_view_shows_per_role_and_per_project_spend():
    # rev 0.3.81: cost_spent feeds proj_cost but had no operator surface. $ opens a viewer with the
    # per-role totals (proj_cost) + per-project totals (reconstructed from cost_spent events) + total.
    from textual.widgets import Static as _Static
    from devharness.console.tui import _ViewerModal

    app = _app()
    bus = app.writer
    bus.emit_sync("cost_spent", {"role": "developer", "amount_usd": 5.0, "task_id": "p1-t0",
                                 "spent_at_millis": 1, "correlation_id": "proj-1"}, "proj-1")
    bus.emit_sync("cost_spent", {"role": "verify_review", "amount_usd": 2.5,
                                 "spent_at_millis": 2, "correlation_id": "proj-1"}, "proj-1")
    bus.emit_sync("cost_spent", {"role": "research", "amount_usd": 1.0,
                                 "spent_at_millis": 3, "correlation_id": "proj-2"}, "proj-2")
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test() as pilot:
        # the state panel shows the grand total
        tui._refresh()
        assert "cost: $8.50" in str(tui.query_one("#state", _Static).render())
        # the $ action opens the detail viewer
        tui.action_list_cost()
        await pilot.pause()
        assert isinstance(tui.screen, _ViewerModal)
        rendered = str(tui.screen.query_one(_Static).render())
        assert "developer" in rendered and "$5.0000" in rendered      # per-role
        assert "proj-1" in rendered and "$7.5000" in rendered          # per-project (5.0 + 2.5)
        assert "TOTAL: $8.5000" in rendered


async def test_cost_view_empty_when_nothing_spent():
    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    logged: list[str] = []
    async with tui.run_test():
        tui._log = logged.append
        assert tui._cost_report() is None
        tui.action_list_cost()
    assert any("no LLM spend" in m for m in logged)


async def test_active_role_reflects_the_running_build_step():
    # rev 0.3.77: nothing emits role_transitioned, so proj_role_state is always (none) — the panel
    # showed "active role: (none)" even during a running developer dispatch, reading as stuck. The
    # active-role line now derives from the live _busy step (mapped to its role), else "(idle)".
    from textual.widgets import Static

    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        tui._busy = "developer dispatch"
        tui._refresh()
        assert "active role: developer" in str(tui.query_one("#state", Static).render())
        tui._busy = "research"
        tui._refresh()
        assert "active role: research" in str(tui.query_one("#state", Static).render())
        tui._busy = None  # idle — the dead projection reads (none), shown as (idle)
        tui._refresh()
        assert "active role: (idle)" in str(tui.query_one("#state", Static).render())


async def test_action_errors_are_logged_not_raised():
    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    logged: list[str] = []
    async with tui.run_test():
        tui._log = logged.append  # capture log output
        tui._reject_spec("only_one_token")                      # malformed -> validation error
        tui._enact_gate_change("not_a_number")                  # malformed -> validation error
        tui._act(lambda: app.signoff().sign("nope"), lambda r: "ok")  # UnknownSpec from the real method
    assert sum("ERROR" in m for m in logged) >= 3


async def test_list_actions_run_on_empty_store():
    # empty lists stay one-line log entries — no modal for nothing (rev 0.3.72)
    from devharness.console.tui import _ViewerModal

    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    logged: list[str] = []
    async with tui.run_test():
        tui._log = logged.append
        tui.action_list_candidates()
        tui.action_list_expired()
        tui.action_list_gate_changes()
        assert not isinstance(tui.screen, _ViewerModal)
    assert any("retro candidates" in m for m in logged)
    assert any("expired trust grants" in m for m in logged)
    assert not any("ERROR" in m for m in logged)


async def test_list_candidates_opens_the_viewer_when_pending_rows_exist():
    # rev 0.3.72: c dumped the candidate JSON into the append-only log — the exact defect the
    # spec viewer (v) already fixed; the list now renders in the same dismissable viewer.
    from textual.widgets import Static as _Static
    from devharness.console.tui import _ViewerModal

    app = _app()
    app.writer.emit_sync("antibody_candidate", {
        "retro_run_correlation_id": "c-r", "signature_name": "gate_deny_injection",
        "pattern_text": "ignore previous instructions", "evidence_event_ids": [],
        "source": "t0", "created_at_millis": 1,
    }, correlation_id="c-r")
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test() as pilot:
        tui.action_list_candidates()
        await pilot.pause()
        assert isinstance(tui.screen, _ViewerModal)
        rendered = str(tui.screen.query_one(_Static).render())
        assert "gate_deny_injection" in rendered  # the rows are actually shown
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(tui.screen, _ViewerModal)  # the way back exists


async def test_sidecar_down_falls_back_to_polling_without_hanging():
    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_RaisingConsumer)
    async with tui.run_test():
        # the follower thread raises immediately and schedules _start_polling on the UI thread
        for _ in range(40):
            if tui._poll_timer is not None:
                break
            await asyncio.sleep(0.05)
    assert tui._poll_timer is not None  # fell back to polling; the test completing proves no hang


def test_follow_loop_marshals_to_ui_thread_per_frame():
    # the load-bearing contract: the follower thread does NO SQLite/widget work itself —
    # it only marshals the frame handler (the sole owning-thread reader) to the UI thread.
    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=lambda: _NFrameConsumer(2))
    calls = []
    tui.call_from_thread = lambda fn, *a, **k: calls.append(fn)
    tui._follow_loop()
    assert calls == [tui._on_frame, tui._on_frame]  # one marshal per frame, only the UI handler


def test_follow_loop_swallows_cancelled_error_on_teardown():
    # call_from_thread against a stopping app raises concurrent.futures.CancelledError;
    # _follow_loop must swallow it (the daemon thread unwinds silently), not propagate.
    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=lambda: _NFrameConsumer(1))

    def _raise(*_a, **_k):
        raise concurrent.futures.CancelledError()

    tui.call_from_thread = _raise
    tui._follow_loop()  # must return cleanly; a propagated CancelledError fails the test


async def test_sign_action_emits_spec_signed_end_to_end():
    app = _app()
    _seed_spec_artifact(app.conn, "spec-9")
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        tui._act(lambda: app.signoff().sign("spec-9"), lambda sid: f"signed {sid}")
    assert any(e.get("spec_id") == "spec-9" for e in _events(app.conn, "spec_signed"))


# --- cut 2: the long-running build steps in thread workers ---


async def test_proxy_bus_routes_emit_to_the_main_bus():
    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    forwarded = []
    async with tui.run_test():
        tui.call_from_thread = lambda fn, *a, **k: forwarded.append((fn, a))
        _ProxyBus(tui).emit_sync("role_transitioned", {"to_role": "x"}, "c1")
    assert forwarded and forwarded[0][0] == app.writer.emit_sync  # routed to the main bus


async def test_concurrent_emits_keep_the_hash_chain_intact(tmp_path):
    # The load-bearing regression: a worker emitting through the proxy WHILE the main
    # thread emits must not corrupt the hash chain (Inv 7) — the proxy funnels every
    # emit_sync onto the one UI thread, so they serialize. verify_chain must still pass.
    from devharness.events.bus import verify_chain

    db = str(tmp_path / "ev.db")
    app = ConsoleApp(db_path=db).connect()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        proxy = _ProxyBus(tui)
        done = threading.Event()

        def worker():
            for i in range(15):
                proxy.emit_sync("role_transitioned", {"to_role": f"w{i}"}, "c1")
            done.set()

        threading.Thread(target=worker, daemon=True).start()
        for i in range(15):
            app.writer.emit_sync("role_transitioned", {"to_role": f"m{i}"}, "c1")
            await asyncio.sleep(0)  # let the UI thread service the proxy's call_from_thread
        for _ in range(200):
            if done.is_set():
                break
            await asyncio.sleep(0.02)
    verify_chain(app.conn)  # raises IntegrityError if the chain was interleaved/corrupted
    assert app.loop_state().event_count >= 30


async def test_run_step_uses_its_own_conn_and_proxies_to_the_main_conn(tmp_path):
    db = str(tmp_path / "ev.db")
    app = ConsoleApp(db_path=db).connect()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        def fn(conn, bus):
            assert conn is not app.conn  # the worker has its OWN connection (for reads)
            bus.emit_sync("role_transitioned", {"to_role": "director"}, "c1")
            return "ok"

        tui._busy = "test"
        worker = tui._run_step("test", fn)
        await worker.wait()
    assert app.loop_state().active_role == "director"  # the proxied event landed on the main conn
    assert tui._busy is None  # _end cleared the slot


async def test_build_step_refused_on_memory_db():
    app = _app()  # :memory: can't WAL
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        assert tui._begin("step") is False


async def test_busy_guard_blocks_a_second_build_step(tmp_path):
    db = str(tmp_path / "ev.db")
    app = ConsoleApp(db_path=db).connect()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        assert tui._begin("first") is True
        assert tui._busy == "first"
        assert tui._begin("second") is False  # build-vs-build blocked


async def test_failing_step_surfaces_error_and_survives(tmp_path):
    db = str(tmp_path / "ev.db")
    app = ConsoleApp(db_path=db).connect()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        def fn(conn, bus):
            raise ValueError("boom")

        tui._busy = "test"
        worker = tui._run_step("test", fn)
        await worker.wait()  # exit_on_error=False + try/except: the app survives
        assert tui._busy is None  # slot cleared even on failure


async def test_on_frame_renders_only_build_events_to_progress(tmp_path):
    from devharness.console.sse import SSEFrame
    from textual.widgets import RichLog

    db = str(tmp_path / "ev.db")
    app = ConsoleApp(db_path=db).connect()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        log = tui.query_one("#progress", RichLog)
        before = len(log.lines)
        tui._on_frame(SSEFrame(seq=1, event_type="verifier_outcome", replayed=False,
                               payload={"verifier": "feature_spec_claim", "passed": True}))
        mid = len(log.lines)
        tui._on_frame(SSEFrame(seq=2, event_type="not_a_progress_event", replayed=False, payload={}))
        after = len(log.lines)
    assert mid > before   # the build event rendered
    assert after == mid    # a non-build event did not


async def test_submit_answer_is_visible_to_a_worker_conn_poll_under_wal(tmp_path):
    # the heart of the research producer/consumer: the operator's submit_answer (main conn)
    # becomes visible to the role's poll on a separate worker connection, under WAL.
    db = str(tmp_path / "ev.db")
    app = ConsoleApp(db_path=db).connect()
    app.writer.emit_sync("research_started", {"research_id": "c1", "topic": "x"}, "c1")
    app.writer.emit_sync(
        "question_asked", {"research_id": "c1", "question_id": "q1", "question_text": "?"}, "c1"
    )
    seen = {}

    def poll():
        # the worker opens its OWN connection in its OWN thread (as the real role does)
        wc = sqlite3.connect(db)
        wc.execute("PRAGMA busy_timeout=5000")
        try:
            for _ in range(200):
                for (payload,) in wc.execute(
                        "SELECT payload FROM events WHERE event_type='question_answered'"):
                    record = json.loads(payload)
                    if record.get("question_id") == "q1":
                        seen["a"] = record.get("answer_text")
                        return
                time.sleep(0.02)
        finally:
            wc.close()

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        tui._answer("the operator answer")  # answers the latest unanswered question (q1)
        for _ in range(80):
            if "a" in seen:
                break
            await asyncio.sleep(0.02)
    poller.join(timeout=2)
    assert seen.get("a") == "the operator answer"


async def test_quit_refused_while_a_build_runs():
    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    logged = []
    async with tui.run_test():
        tui._log = logged.append
        tui._busy = "developer dispatch"
        tui.action_quit()  # must NOT tear down mid-build (would strand the write lock)
        assert tui.is_running
    assert any("can't quit" in m for m in logged)


async def test_polling_fallback_renders_per_event_progress(tmp_path):
    from textual.widgets import RichLog

    db = str(tmp_path / "ev.db")
    app = ConsoleApp(db_path=db).connect()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        log = tui.query_one("#progress", RichLog)
        tui._start_polling()  # the sidecar-down fallback arms an event-log tail
        before = len(log.lines)
        app.writer.emit_sync(
            "question_asked", {"research_id": "r1", "question_id": "q1", "question_text": "?"}, "c1"
        )
        tui._poll_events()  # the next poll tick surfaces the new build event
        after = len(log.lines)
    assert after > before


# --- cut 3: build-target scoping ---


async def test_set_target_creates_and_initializes(tmp_path):
    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    new = tmp_path / "fresh"  # does not exist yet
    async with tui.run_test():
        tui._set_target(f"{new} | python -m pytest -q")
        assert tui._target_path == str(new)
        assert tui._test_command == ["python", "-m", "pytest", "-q"]
        # idempotent: setting it again (already a repo with a HEAD) still succeeds
        tui._set_target(str(new))
        assert tui._target_path == str(new)
        assert tui._test_command is None
    # T created the dir, git-initialized it, and gave it a HEAD to branch from
    assert new.is_dir()
    assert subprocess.run(["git", "-C", str(new), "rev-parse", "HEAD"], capture_output=True).returncode == 0
    # rev 0.3.58: a T-created repo is seeded with a cache-covering .gitignore (a gitignore-less
    # target let worker test runs surface __pycache__ as scope violations)
    assert "__pycache__/" in (new / ".gitignore").read_text()


async def _seed_target_store(path, target):
    """A file-backed store carrying one build_target_set for `target`."""
    a = ConsoleApp(db_path=str(path)).connect()
    a.writer.emit_sync("build_target_set", {"target_path": str(target),
                                            "test_command": ["python", "-m", "pytest", "-q"],
                                            "correlation_id": "console"}, "console")
    a.conn.close()


async def test_switch_project_reconnects_to_another_store(tmp_path):
    # rev 0.3.75: the operator drives a different project without quitting + relaunching with a new
    # DEVHARNESS_DB — P discovers the sibling stores and reconnects to the chosen one.
    var = tmp_path / "var"
    var.mkdir()
    repo_b = tmp_path / "projB"
    repo_b.mkdir()
    subprocess.run(["git", "-C", str(repo_b), "init", "-q"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_b), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "--allow-empty", "-m", "x"], check=True, capture_output=True)
    await _seed_target_store(var / "projA.db", tmp_path / "projA")
    await _seed_target_store(var / "projB.db", repo_b)

    app = ConsoleApp(db_path=str(var / "projA.db")).connect()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        found = tui._discover_projects()
        names = {n for (_p, n, _t) in found}
        assert {"projA", "projB"} <= names
        # switch to projB by list index
        idx = [n for (_p, n, _t) in found].index("projB") + 1
        logged: list[str] = []
        tui._log = logged.append
        tui._switch_choices = [p for (p, _n, _t) in found]
        tui._switch_project_pick(str(idx))
        assert Path(tui._console.db_path).stem == "projB"  # reconnected
        assert tui._target_path == str(repo_b)  # projB's target restored (valid git repo)
    assert any("switched to projB" in m for m in logged)


async def test_switch_project_refused_mid_build(tmp_path):
    var = tmp_path / "var"; var.mkdir()
    await _seed_target_store(var / "p.db", tmp_path / "p")
    app = ConsoleApp(db_path=str(var / "p.db")).connect()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        tui._busy = "research"
        logged: list[str] = []
        tui._log = logged.append
        tui.action_switch_project()
        assert any("can't switch" in m for m in logged)
        assert Path(tui._console.db_path).stem == "p"  # unchanged


async def test_new_project_creates_store_sets_target_and_starts_research(tmp_path):
    var = tmp_path / "var"; var.mkdir()
    await _seed_target_store(var / "seed.db", tmp_path / "seed")
    repo = tmp_path / "brandnew"  # does not exist — _set_target creates+inits it
    app = ConsoleApp(db_path=str(var / "seed.db")).connect()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    started = {}
    async with tui.run_test():
        tui._start_research = lambda seed: started.update(seed=seed)  # don't spawn a real worker
        tui._new_project(f"wc | {repo} | a stdlib word-count CLI")
        assert Path(tui._console.db_path).stem == "wc"  # switched to the new store
        assert (var / "wc.db").exists()
        assert tui._target_path == str(repo)  # target set on the new store
        assert started.get("seed") == "a stdlib word-count CLI"  # research started with the seed
    assert repo.is_dir()  # the repo was created + git-initialized by _set_target


async def test_developer_surface_passes_the_set_target():
    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    captured = {}
    async with tui.run_test():
        tui._developer_factory = lambda conn, bus, **kw: captured.update(kw)
        tui._target_path = "../dedup"
        tui._test_command = ["python", "-m", "pytest", "-q"]
        tui._developer_surface(None, None)
        assert captured == {"auto_retro": True, "base_path": "../dedup",
                            "test_command": ["python", "-m", "pytest", "-q"]}
        captured.clear()
        tui._target_path = None
        tui._test_command = None
        tui._developer_surface(None, None)
        # no target -> ConsoleDeveloper's own env/defaults apply; auto_retro always on (rev 0.4.23)
        assert captured == {"auto_retro": True}


async def test_set_target_persists_and_a_new_console_restores_it(tmp_path):
    # a console restart used to reset the target to None, forcing re-entry — one stale re-entry
    # landed an entire build in the WRONG project's repo. T now emits build_target_set and a fresh
    # TUI on the same store restores it (validated: still a git repo with a HEAD).
    app = _app()
    new = tmp_path / "proj"
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        tui._set_target(f"{new} | python -m pytest -q")
    events = [json.loads(p) for (p,) in app.conn.execute(
        "SELECT payload FROM events WHERE event_type='build_target_set'")]
    assert events and events[-1]["target_path"] == str(new)
    assert events[-1]["test_command"] == ["python", "-m", "pytest", "-q"]

    fresh = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)  # same store, new console
    async with fresh.run_test():
        assert fresh._target_path == str(new)
        assert fresh._test_command == ["python", "-m", "pytest", "-q"]


async def test_restore_skips_a_stale_target_and_empty_command_roundtrips_to_none(tmp_path):
    app = _app()
    gone = tmp_path / "was-here"
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        tui._set_target(str(gone))  # no | command -> _test_command is None -> event stores []
    import os
    import shutil
    import stat

    def _chmod_retry(func, p, exc):  # Windows: git objects are read-only
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(gone, onexc=_chmod_retry)  # the target vanishes between sessions

    fresh = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with fresh.run_test():
        assert fresh._target_path is None  # stale path NOT restored (and NOT re-created)
    assert not gone.exists()  # restore must never _prepare_target a stale path back into existence

    # and with the path still present, the []-command event round-trips to None, not []
    still = tmp_path / "still-here"
    tui2 = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui2.run_test():
        tui2._set_target(str(still))
    fresh2 = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with fresh2.run_test():
        assert fresh2._target_path == str(still)
        assert fresh2._test_command is None


async def test_input_modal_joins_a_multiline_paste():
    # Textual's Input keeps only splitlines()[0] of a paste — a two-line seed pasted into R's
    # prompt was silently truncated mid-sentence, twice, live. The modal's input joins instead.
    # MUST post through the real dispatch pump, NOT call the handler directly: Textual invokes
    # _on_paste for EVERY class in the MRO, and a direct-call test passed while the real dispatch
    # ran Input's handler too and inserted every paste twice (caught live on the next build).
    from textual import events as textual_events
    from devharness.console.tui import _InputModal, _JoinPasteInput

    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test() as pilot:
        tui.push_screen(_InputModal("seed:"))
        await pilot.pause()
        box = tui.screen.query_one(_JoinPasteInput)
        box.focus()
        await pilot.pause()
        box.post_message(textual_events.Paste("line one wraps\nand continues here\n"))
        await pilot.pause()
        assert box.value == "line one wraps and continues here"

        box.value = ""
        box.post_message(textual_events.Paste("a single-line paste"))
        await pilot.pause()
        assert box.value == "a single-line paste"  # inserted exactly once, never doubled


async def test_review_spec_opens_a_dismissable_viewer_not_the_log():
    # v used to dump the whole spec JSON into the append-only #log pane — prior lines scrolled
    # away with no keyboard way back. It now opens a scrollable viewer modal; Escape closes it.
    from textual.widgets import Static as _Static
    from devharness.console.tui import _ViewerModal

    app = _app()
    _seed_spec_artifact(app.conn, "spec-9")
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test() as pilot:
        tui._review_spec("spec-9")
        await pilot.pause()
        assert isinstance(tui.screen, _ViewerModal)
        rendered = str(tui.screen.query_one(_Static).render())
        assert '"success_criteria"' in rendered  # the body is actually shown
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(tui.screen, _ViewerModal)  # Escape closes — the way back exists


async def test_viewer_renders_bracketed_spec_body_literally():
    # rev 0.3.62: a spec whose JSON contained ["packaging==24.0."] parsed as Textual MARKUP and
    # crashed the whole app at compositor reflow — outside any action handler, so the per-action
    # error logging never saw it (live, a prior drive). Store-derived text renders literally.
    from textual.widgets import Static as _Static
    from devharness.console.tui import _ViewerModal

    app = _app()
    payload = {
        "problem": "compare versions", "scope": "s", "non_goals": [], "interfaces": ["x"],
        "success_criteria": ['pin packaging==24.0 in requirements.txt: ["packaging==24.0."]'],
        "verification_plan": "v", "assumptions": [], "correlation_id": "proj-1",
    }
    app.conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES ('spec-b', 'spec', 1, ?, 'proj-1', 100, 0)",
        (json.dumps(payload),),
    )
    app.conn.commit()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test() as pilot:
        tui._review_spec("spec-b")
        await pilot.pause()  # the crash was at reflow — surviving this pause IS the regression
        assert isinstance(tui.screen, _ViewerModal)
        rendered = str(tui.screen.query_one(_Static).render())
        assert 'packaging==24.0.' in rendered  # shown literally, not eaten as markup


async def test_viewer_title_with_brackets_does_not_crash():
    # border_title parses markup UNCONDITIONALLY (the widget's markup=False does not cover it) —
    # a store-derived/operator-typed title must go in as pre-built Content (the review's catch).
    from devharness.console.tui import _ViewerModal

    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test() as pilot:
        tui.push_screen(_ViewerModal("spec [packaging==24.0.]", "body"))
        await pilot.pause()
        assert isinstance(tui.screen, _ViewerModal)


async def test_input_modal_prompt_keeps_literal_brackets():
    # the A-prompt embeds LLM question text; also, markup was EATING the W prompt's literal
    # "[task_id]" hint — operators saw "correlation_id " (a live display bug this fix cures).
    from textual.widgets import Label as _Label
    from devharness.console.tui import _InputModal

    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test() as pilot:
        tui.push_screen(_InputModal("correlation_id [task_id]"))
        await pilot.pause()
        assert "[task_id]" in str(tui.screen.query_one(_Label).render())


async def test_state_panel_renders_bracketed_reason_literally():
    # _next_hint embeds terminal reasons (untrusted store text) into the #state Static — a
    # bracketed reason must render literally, not crash the reflow as markup (rev 0.3.62)
    from textual.widgets import Static as _Static

    app = _app()
    bus = app.writer
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test() as pilot:
        bus.emit_sync("research_started", {"question": "x"}, "c1")
        _draft_3task_plan(app)
        bus.emit_sync("terminal_outcome", {"task_id": "c1-t0", "outcome": "rejected",
                                           "detail": 'pin ["packaging==24.0."] failed', "reason": "",
                                           "correlation_id": "c1", "terminated_at_millis": 1}, "c1")
        tui._refresh()
        await pilot.pause()  # surviving the reflow with bracketed store text IS the assertion
        text = str(tui.query_one("#state", _Static).render())
        assert "rejected" in text and "packaging==24.0." in text


async def test_on_mount_announces_a_brand_new_store(tmp_path):
    # rev 0.3.63: a fresh empty store at an unintended path is contamination-shaped (the
    # wrong-cwd relative-DEVHARNESS_DB incident) — creation is announced, never silent.
    app = ConsoleApp(db_path=str(tmp_path / "new.db")).connect()
    assert app.store_created is True
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    logged: list[str] = []
    tui._log = logged.append  # capture before mount — the announcement fires in on_mount
    async with tui.run_test() as pilot:
        await pilot.pause()
    assert any("NEW EMPTY event store" in m and str(tmp_path / "new.db") in m for m in logged)


async def test_on_mount_is_silent_for_an_existing_store(tmp_path):
    db = str(tmp_path / "seen.db")
    ConsoleApp(db_path=db).connect()  # born here...
    app = ConsoleApp(db_path=db).connect()  # ...reopened here: no announcement
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    logged: list[str] = []
    tui._log = logged.append
    async with tui.run_test() as pilot:
        await pilot.pause()
    assert not any("NEW EMPTY" in m for m in logged)


async def test_review_spec_unknown_id_logs_error_and_opens_no_viewer():
    from devharness.console.tui import _ViewerModal

    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test() as pilot:
        tui._review_spec("nope")
        await pilot.pause()
        assert not isinstance(tui.screen, _ViewerModal)  # error surfaced to the log, no modal


async def test_next_hint_guides_through_the_loop():
    app = _app()
    bus = app.writer
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        assert "research" in tui._next_hint().lower()  # nothing drafted yet -> research
        bus.emit_sync("spec_drafted", {"spec_id": "spec-1", "title": "x"}, "c1")
        assert tui._next_hint().startswith("s ")  # an unsigned drafted spec -> sign
        bus.emit_sync("spec_signed", {"spec_id": "spec-1", "signer": "op", "signed_at_millis": 1}, "c1")
        assert tui._next_hint().startswith("D ")  # signed, no plan -> plan

        # the signed spec isn't an artifact row here, so _latest_correlation falls back to research_started
        bus.emit_sync("research_started", {"question": "x"}, "c1")
        plan = {"plan_id": "plan-1", "spec_artifact_id": "spec-1", "correlation_id": "c1",
                "created_at_millis": 100,
                "tasks": [{"task_id": "c1-t0", "task_class": "feature", "description": "x",
                           "scope_boundary": [], "dependencies": [], "correlation_id": "c1"}]}
        app.conn.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
            "correlation_id, created_at_millis, signed) VALUES ('plan-1','plan',1,?,?,100,0)",
            (json.dumps(plan), "c1"))
        app.conn.commit()
        bus.emit_sync("plan_drafted", {"plan_id": "plan-1"}, "c1")
        assert "build" in tui._next_hint().lower()  # a pending task -> build
        # rejected task: assemble would refuse NotAllCompleted, so the hint must NOT recommend M
        bus.emit_sync("terminal_outcome", {"task_id": "c1-t0", "outcome": "rejected", "detail": "",
                                           "correlation_id": "c1", "terminated_at_millis": 1}, "c1")
        assert "rejected" in tui._next_hint() and not tui._next_hint().startswith("M ")
        # a later completed terminal wins (latest-by-seq) -> assemble
        bus.emit_sync("terminal_outcome", {"task_id": "c1-t0", "outcome": "completed", "detail": "",
                                           "correlation_id": "c1", "terminated_at_millis": 2}, "c1")
        assert tui._next_hint().startswith("M ")  # all tasks completed -> assemble
        # M already ran (project_assembled recorded) -> the hint must not keep recommending M
        bus.emit_sync("project_assembled", {
            "plan_id": "plan-1", "final_task_id": "c1-t0", "final_branch": "devharness/c1-t0",
            "merge_sha": "deadbeef", "target_path": "../proj", "merged_into_branch": "main",
            "correlation_id": "c1",
        }, "c1")
        assert tui._next_hint().startswith("done")


async def test_next_hint_and_answer_prompt_show_the_readable_pending_question():
    app = _app()
    bus = app.writer
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        bus.emit_sync("research_started", {"question": "x"}, "c1")
        payload = json.dumps({
            "assumed_objective": "build a thing",
            "divergence_points": [
                {"question": "top 5 of what, and what's the tie-break rule?"},
                {"question": "and what about duplicate counts?"},  # rev 0.4.12: EVERY question
            ],
        })
        bus.emit_sync("question_asked", {
            "research_id": "c1", "question_id": "c1-q0", "question_text": payload,
        }, "c1")

        # restart-proof: this is a fresh TUI instance reading the same DB, nothing live-streamed —
        # exactly the "I restarted and don't know the question" scenario.
        hint = tui._next_hint()
        assert hint.startswith("A — answer:")
        assert "top 5 of what" in hint  # the hint stays the one-line extraction

        # rev 0.4.12: the answer prompt renders the COMPLETE question — the 400-char summary showed
        # only the first divergence question, so the operator answered questions they never saw.
        prompt = tui._answer_prompt_text()
        assert "top 5 of what" in prompt
        assert "duplicate counts" in prompt
        assert "{" not in prompt  # readable, not the raw JSON payload
        assert prompt.endswith("your answer:")


async def test_answer_finds_a_second_correlation_interview():
    # rev 0.3.69: a store with a SIGNED spec on c-old (the finished first build) starts a NEW
    # research run on c-new whose interview asks a question. The signed-spec-scoped lookup made
    # that question invisible — live on a dependency_bump drive, A said "no unanswered
    # question" while research blocked forever on the 0.3.68 confirmation turn.
    app = _app()
    bus = app.writer
    _seed_spec_artifact(app.conn, "spec-old")  # correlation proj-1
    bus.emit_sync("spec_signed", {"spec_id": "spec-old", "signer": "op", "signed_at_millis": 1},
                  "proj-1")
    bus.emit_sync("research_started", {"research_id": "c-new", "topic": "bump packaging"}, "c-new")
    bus.emit_sync("question_asked", {"research_id": "c-new", "question_id": "c-new-q0",
                                     "question_text": "Confirm scope before I draft the spec"},
                  "c-new")
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        assert tui._latest_unanswered_question() == "c-new-q0"
        assert "Confirm scope" in tui._next_hint()  # the state panel names it too
        logged: list[str] = []
        tui._log = logged.append
        tui._answer("ok")  # must submit, not log "no unanswered question"
    assert not any("no unanswered question" in m for m in logged)
    answered = _events(app.conn, "question_answered")
    assert [a["question_id"] for a in answered] == ["c-new-q0"]
    assert answered[0]["answer_text"] == "ok"


async def test_abandoned_interview_stops_hijacking_once_its_spec_drafts():
    # the original orphan concern, preserved: once the latest research run has drafted its spec,
    # its stale unanswered question no longer owns the A default — scope returns to the signed
    # spec's correlation.
    app = _app()
    bus = app.writer
    _seed_spec_artifact(app.conn, "spec-old")
    bus.emit_sync("spec_signed", {"spec_id": "spec-old", "signer": "op", "signed_at_millis": 1},
                  "proj-1")
    bus.emit_sync("research_started", {"research_id": "c-new", "topic": "t"}, "c-new")
    bus.emit_sync("question_asked", {"research_id": "c-new", "question_id": "c-new-q0",
                                     "question_text": "?"}, "c-new")
    # the c-new run drafts its spec (interview over; the pending q0 is now moot)
    app.conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES ('spec-new', 'spec', 1, '{}', 'c-new', 200, 0)")
    app.conn.commit()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        assert tui._latest_unanswered_question() is None


async def test_next_hint_surfaces_a_pending_question_while_research_is_running():
    # rev 0.3.74: during research the worker polls silently for the answer, so _busy=="research" the
    # whole time — a pending mid-research question was hidden behind the bare "running: research" line
    # and the panel read as stuck. It now surfaces the question even while busy.
    app = _app()
    bus = app.writer
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        bus.emit_sync("research_started", {"research_id": "c1", "topic": "x"}, "c1")
        bus.emit_sync("question_asked", {
            "research_id": "c1", "question_id": "c1-q0",
            "question_text": "top 5 of what — most frequent, longest?"}, "c1")
        tui._busy = "research"  # what _begin('research') sets for the whole run
        hint = tui._next_hint()
        assert "A" in hint and "research is waiting" in hint
        assert "top 5 of what" in hint
        assert not hint.startswith("running:")  # no longer reads as stuck

        # a NON-research busy step keeps the plain running line (only research asks questions)
        tui._busy = "developer dispatch"
        assert tui._next_hint() == "running: developer dispatch  (ctrl+x to cancel)"

        # research busy but NO pending question (e.g. before q0, or after answering) → plain line
        bus.emit_sync("question_answered", {"question_id": "c1-q0", "answer_text": "ok",
                                            "correlation_id": "c1", "answered_at_millis": 2}, "c1")
        tui._busy = "research"
        assert tui._next_hint() == "running: research  (ctrl+x to cancel)"


async def test_next_hint_falls_back_on_non_json_question_text():
    app = _app()
    bus = app.writer
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        bus.emit_sync("research_started", {"question": "x"}, "c1")
        bus.emit_sync("question_asked", {
            "research_id": "c1", "question_id": "c1-q0", "question_text": "plain text, not JSON",
        }, "c1")

        hint = tui._next_hint()
        assert hint.startswith("A — answer:")
        assert "plain text, not JSON" in hint


def _draft_3task_plan(app, cid="c1"):
    bus = app.writer
    bus.emit_sync("spec_drafted", {"spec_id": "spec-1", "title": "x"}, cid)
    bus.emit_sync("spec_signed", {"spec_id": "spec-1", "signer": "op", "signed_at_millis": 1}, cid)
    plan = {"plan_id": "plan-1", "spec_artifact_id": "spec-1", "correlation_id": cid,
            "created_at_millis": 100,
            "tasks": [{"task_id": f"{cid}-t{i}", "task_class": "feature", "description": "x",
                       "scope_boundary": [], "dependencies": [], "correlation_id": cid}
                      for i in range(3)]}
    app.conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES ('plan-1','plan',1,?,?,100,0)",
        (json.dumps(plan), cid))
    app.conn.commit()
    bus.emit_sync("plan_drafted", {"plan_id": "plan-1"}, cid)


async def test_next_hint_warns_when_blocked_task_has_pending_siblings():
    # 3-task plan: t0 completes, t1 rejects, t2 is still pending (never dispatched) — the
    # multi-task mid-plan block a live-driving session actually hit (M — assemble silently kept
    # being suggested-as-"W — build the next task" with zero indication t1 needed attention).
    app = _app()
    bus = app.writer
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        bus.emit_sync("research_started", {"question": "x"}, "c1")
        _draft_3task_plan(app)
        bus.emit_sync("terminal_outcome", {"task_id": "c1-t0", "outcome": "completed", "detail": "",
                                           "correlation_id": "c1", "terminated_at_millis": 1}, "c1")
        bus.emit_sync("terminal_outcome", {"task_id": "c1-t1", "outcome": "rejected",
                                           "detail": "test failure: 2 failed", "reason": "",
                                           "correlation_id": "c1", "terminated_at_millis": 2}, "c1")

        hint = tui._next_hint()
        assert "c1-t1" in hint
        assert "rejected" in hint
        assert "skip" in hint.lower()
        assert not hint.startswith("W — build")  # must not read as an ordinary "keep going" hint
        assert "test failure: 2 failed" in hint  # the reason/detail is surfaced, not just the outcome


async def test_next_hint_warns_on_an_aborted_task_too():
    # the "blocked" branch isn't keyed on the literal word "rejected" — aborted blocks the same way.
    app = _app()
    bus = app.writer
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        bus.emit_sync("research_started", {"question": "x"}, "c1")
        _draft_3task_plan(app)
        bus.emit_sync("terminal_outcome", {"task_id": "c1-t0", "outcome": "aborted",
                                           "detail": "cap_exceeded:usd", "reason": "",
                                           "correlation_id": "c1", "terminated_at_millis": 1}, "c1")

        hint = tui._next_hint()
        assert "c1-t0" in hint and "aborted" in hint
        assert "skip" in hint.lower()


async def test_next_hint_names_the_retry_command_when_all_tasks_settled_but_one_rejected():
    # all N tasks already have SOME terminal (no pending siblings left to skip to) but one is
    # rejected, not completed — this is the state a live session hit after W raised
    # AllTasksSettled: the old text ("assemble blocked until every task completes") didn't say
    # HOW to unblock it. The retry command must be spelled out here too, not just in the
    # blocked-with-pending-siblings branch.
    app = _app()
    bus = app.writer
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        bus.emit_sync("research_started", {"question": "x"}, "c1")
        _draft_3task_plan(app)
        for i in (0, 1):
            bus.emit_sync("terminal_outcome", {"task_id": f"c1-t{i}", "outcome": "completed",
                                               "detail": "", "correlation_id": "c1",
                                               "terminated_at_millis": i + 1}, "c1")
        bus.emit_sync("terminal_outcome", {"task_id": "c1-t2", "outcome": "rejected",
                                           "detail": "verifier_failed", "reason": "",
                                           "correlation_id": "c1", "terminated_at_millis": 3}, "c1")

        hint = tui._next_hint()
        assert "c1-t2" in hint and "rejected" in hint
        # W's prompt is 'correlation_id [task_id]' (two tokens) -- a lone task_id gets parsed as
        # the correlation_id instead (the exact bug a live session hit), so the hint must spell
        # out BOTH tokens, not just the task_id alone.
        assert "c1 c1-t2" in hint

        tui._busy = "developer dispatch"
        assert tui._next_hint().startswith("running:")  # a running build overrides the hint


async def test_discover_omits_foreign_dbs(tmp_path):
    # rev 0.4.13: the MCP servers' own databases (parallax.db/reasoning.db in the VPS var/) must
    # not be offered as projects — switching to one would migrate devharness schema into it.
    var = tmp_path / "var"
    var.mkdir()
    await _seed_target_store(var / "projA.db", tmp_path / "projA")
    foreign = var / "parallax.db"
    conn = sqlite3.connect(str(foreign))
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    app = ConsoleApp(db_path=str(var / "projA.db")).connect()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    async with tui.run_test():
        names = {n for (_p, n, _t) in tui._discover_projects()}
        assert "projA" in names and "parallax" not in names


async def test_retro_run_action_drains_via_shared_helper(tmp_path, monkeypatch):
    # rev 0.4.23: `L` runs the §S7 explicit retro drain against the connected store through the shared
    # run_retro_drain (the same helper the post-build auto-drain and the panel route use), as a
    # thread-worker build step (own read conn; emits proxied to the main-thread writer).
    from devharness.console import tui as tui_mod

    db = str(tmp_path / "ev.db")
    app = ConsoleApp(db_path=db).connect()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    called = {}

    def fake_drain(conn, bus, **kw):
        called["worker_conn"] = conn is not app.conn
        return {"summary": "2 terminal(s) analyzed · 0 signal(s)", "terminals": ["t1", "t2"],
                "signals": [], "halted": False, "halt_reason": "", "held": False}

    monkeypatch.setattr(tui_mod, "run_retro_drain", fake_drain)
    async with tui.run_test():
        assert ("L", "retro_run", "retro run") in ConsoleTUI.BINDINGS
        tui.action_retro_run()
        assert tui._busy == "retro run"
        await tui._active_worker.wait()
        assert tui._busy is None
    assert called["worker_conn"] is True  # the drain ran on the worker's own connection
