"""Panel backend tests: the single-writer serialization (the sharpest risk), the build single-flight
guard, the ported ``→ next`` hint state machine, and the HTTP surface over the action layer."""

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request

import pytest

from devharness.panel.server import Panel, PanelServer
from devharness.panel.worker import BuildRunner, BusyError
from devharness.panel.writer import PanelWriter


def _emit_n(writer, role, n):
    for i in range(n):
        writer.emit_sync("cost_spent",
                         {"role": role, "amount_usd": 0.01, "correlation_id": "c"},
                         correlation_id="c")


def test_writer_serializes_concurrent_emits_without_forking_the_chain(tmp_path):
    """20 threads emitting concurrently through the one PanelWriter must leave an intact hash chain:
    each event's prev_hash equals the previous event's hash (a forked chain is the failure mode a
    naive multi-connection writer would produce — emit_sync is a non-atomic read-then-insert)."""
    db = str(tmp_path / "w.db")
    writer = PanelWriter(db)
    threads = [threading.Thread(target=_emit_n, args=(writer, f"r{i}", 10)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    writer.close()

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT seq, prev_hash, hash FROM events ORDER BY seq").fetchall()
    assert len(rows) == 200
    prev = None
    seen_prev = set()
    for _seq, prev_hash, h in rows:
        if prev is not None:
            assert prev_hash == prev, "hash chain forked — concurrent emits interleaved"
        assert prev_hash not in seen_prev, "duplicate prev_hash — two events chained off the same parent"
        seen_prev.add(prev_hash)
        prev = h


def test_single_flight_rejects_a_second_build(tmp_path):
    db = str(tmp_path / "s.db")
    writer = PanelWriter(db)
    runner = BuildRunner(db, writer)
    release = threading.Event()
    started = threading.Event()

    def blocking_step(conn, bus, cancel):
        started.set()
        release.wait(timeout=5)
        return "done"

    job1 = runner.submit("dispatch", blocking_step)
    assert started.wait(timeout=2)
    assert runner.busy_label == "dispatch"
    with pytest.raises(BusyError):
        runner.submit("dispatch", blocking_step)  # second build refused
    release.set()
    for _ in range(50):
        if runner.busy_label is None:
            break
        time.sleep(0.05)
    assert runner.busy_label is None  # slot released
    assert runner.job(job1)["status"] == "done"
    # a fresh build now succeeds
    release2 = threading.Event()
    release2.set()
    runner.submit("dispatch", lambda c, b, x: "ok")
    writer.close()


def test_single_flight_release_survives_a_step_error(tmp_path):
    db = str(tmp_path / "e.db")
    writer = PanelWriter(db)
    runner = BuildRunner(db, writer)

    def boom(conn, bus, cancel):
        raise RuntimeError("kaboom")

    job = runner.submit("plan", boom)
    for _ in range(50):
        if runner.busy_label is None:
            break
        time.sleep(0.05)
    assert runner.busy_label is None, "a step error must still release the build slot"
    j = runner.job(job)
    assert j["status"] == "error" and "kaboom" in j["error"]
    writer.close()


def test_next_hint_state_machine(tmp_path):
    from devharness.panel import state as pstate
    db = str(tmp_path / "h.db")
    writer = PanelWriter(db)
    conn = sqlite3.connect(db)

    # fresh store: no spec at all
    assert pstate.next_hint(conn, target_path=None, busy_label=None).startswith("set a build target")
    # busy overrides
    assert pstate.next_hint(conn, target_path=None, busy_label="director plan").startswith("running:")
    # an unsigned drafted spec -> sign
    writer.emit_sync("spec_drafted", {"spec_id": "spec-1", "correlation_id": "c"}, correlation_id="c")
    assert pstate.next_hint(conn, target_path=None, busy_label=None) == "sign the drafted spec"
    writer.close()


def test_next_action_token_tracks_the_hint(tmp_path):
    """rev 0.4.3: the machine token the UI gates/glows buttons from — same state machine as the hint."""
    from devharness.panel import state as pstate
    db = str(tmp_path / "a.db")
    writer = PanelWriter(db)
    conn = sqlite3.connect(db)

    def action(busy=None):
        return pstate._hint_and_action(conn, target_path=None, busy_label=busy)[1]

    assert action() == "research"                      # fresh store
    assert action(busy="director plan") == "busy"      # a step holds the slot
    writer.emit_sync("spec_drafted", {"spec_id": "spec-1", "correlation_id": "c"}, correlation_id="c")
    assert action() == "sign"                          # unsigned draft awaits the operator
    # research parked on a question: 'answer' must WIN over 'busy' — the Answer POST is the one
    # action live while the step runs; a 'busy' token would grey out the only useful button.
    writer.emit_sync("research_started", {"correlation_id": "c2"}, correlation_id="c2")
    writer.emit_sync("question_asked", {"question_id": "q1", "research_id": "r1",
                                        "question_text": "scope?", "correlation_id": "c2"},
                     correlation_id="c2")
    assert action(busy="research") == "answer"
    writer.close()


def _seed_plan(writer, conn, tasks, correlation_id="c"):
    """A research correlation + a drafted plan artifact carrying ``tasks`` (the director's shape)."""
    writer.emit_sync("research_started", {"correlation_id": correlation_id},
                     correlation_id=correlation_id)
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES ('plan-1','plan',1,?,?,1,0)",
        (json.dumps({"tasks": tasks}), correlation_id))
    conn.commit()
    writer.emit_sync("plan_drafted", {"plan_id": "plan-1", "correlation_id": correlation_id},
                     correlation_id=correlation_id)


def test_plan_tasks_rows_carry_contextual_action_state(tmp_path):
    """rev 0.4.3: the tappable task list — outcome/reason per row, Build withheld until every
    declared dependency is completed (an out-of-order explicit dispatch builds against a tree
    missing its dependencies' code), certifiable mirrors certify's admission preconditions."""
    from devharness.panel import state as pstate
    db = str(tmp_path / "t.db")
    writer = PanelWriter(db)
    conn = sqlite3.connect(db)
    _seed_plan(writer, conn, [
        {"task_id": "t1", "description": "scaffold", "dependencies": []},
        {"task_id": "t2", "description": "feature x", "dependencies": ["t1"]},
        {"task_id": "t3", "description": "feature y", "dependencies": ["t1"]},
        {"task_id": "t4", "description": "polish", "dependencies": ["t2"]},
    ])
    writer.emit_sync("terminal_outcome", {"task_id": "t1", "outcome": "completed", "detail": "",
                                          "correlation_id": "c"}, correlation_id="c")
    writer.emit_sync("terminal_outcome", {"task_id": "t2", "outcome": "rejected",
                                          "reason": "verifier said no", "detail": "",
                                          "correlation_id": "c"}, correlation_id="c")

    rows = {r["task_id"]: r for r in pstate.plan_tasks(conn, busy=False)}
    assert rows["t1"]["outcome"] == "completed" and "reason" not in rows["t1"]
    assert rows["t2"]["outcome"] == "rejected" and rows["t2"]["reason"] == "verifier said no"
    assert rows["t3"]["buildable"] is True      # its dependency (t1) completed
    assert rows["t4"]["buildable"] is False     # its dependency (t2) is blocked, not completed
    assert rows["t3"]["certifiable"] is False   # never started

    # a started task with a verifier pass and no terminal is the certify recovery state...
    writer.emit_sync("task_started", {"task_id": "t3", "role": "developer", "worktree_path": "/wt",
                                      "correlation_id": "c", "started_at_millis": 1},
                     correlation_id="c")
    writer.emit_sync("verifier_outcome", {"task_id": "t3", "verifier": "test_suite",
                                          "passed": True, "detail": ""}, correlation_id="c")
    assert pstate.plan_tasks(conn, busy=False)[2]["certifiable"] is True
    # ...but only when idle — mid-dispatch the loop itself is about to certify (no glowing decoy)
    assert pstate.plan_tasks(conn, busy=True)[2]["certifiable"] is False
    writer.close()


def test_snapshot_carries_tasks_unsigned_spec_and_next_action(tmp_path):
    from devharness.panel import state as pstate
    db = str(tmp_path / "s.db")
    writer = PanelWriter(db)
    conn = sqlite3.connect(db)
    snap = pstate.snapshot(conn, target_path=None, test_command=None,
                           busy_label=None, busy_job=None)
    assert snap["tasks"] is None and snap["unsigned_spec_id"] is None
    assert snap["next_action"] == "research"
    writer.emit_sync("spec_drafted", {"spec_id": "spec-9", "correlation_id": "c"},
                     correlation_id="c")
    snap = pstate.snapshot(conn, target_path=None, test_command=None,
                           busy_label=None, busy_job=None)
    assert snap["unsigned_spec_id"] == "spec-9" and snap["next_action"] == "sign"
    writer.close()


def test_default_db_picks_the_most_recently_written_store(tmp_path):
    """rev 0.4.4: launched without DEVHARNESS_DB, the panel opens the store the operator last worked
    in (newest mtime — every emit touches the file), NOT the legacy fixed name; the old default
    silently opened the June-era store and greeted the operator with a dead plan's red warning."""
    import os
    from pathlib import Path

    from devharness.panel.server import DEFAULT_DB, _default_db

    old = tmp_path / "devharness.db"
    new = tmp_path / "sample.db"
    # rev 0.4.13: candidates must be REAL stores (an empty file now fails the is_event_store
    # gate by design); a fresh migrated store has an empty events table -> activity None -> the
    # mtime-ranking assertions below stay meaningful.
    for pth in (old, new):
        w = PanelWriter(str(pth))
        w.close()
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    assert _default_db(tmp_path) == str(new)
    # no stores at all -> the fixed name under the SAME anchored root (first run, created loud)
    empty = tmp_path / "empty"
    assert _default_db(empty) == str(empty / Path(DEFAULT_DB).name)


def test_default_db_ranks_by_event_activity_not_file_mtime(tmp_path):
    """rev 0.4.5: mere open/close of a WAL store checkpoints and bumps its mtime with ZERO events
    written — the panel itself laundered the stale legacy store's age that way minutes after the
    mtime heuristic shipped. Ranking must follow the newest event timestamp, so a stale store with
    a freshly-touched file still loses to the store where work actually happened last."""
    import os

    from devharness.panel.server import _default_db

    stale = tmp_path / "legacy.db"
    active = tmp_path / "current.db"
    for path, at in ((stale, 1_000), (active, 2_000)):
        w = PanelWriter(str(path))
        w.emit_sync("cost_spent", {"role": "developer", "amount_usd": 0.01,
                                   "spent_at_millis": at, "correlation_id": "c"},
                    correlation_id="c")
        w.close()
    now = time.time()
    os.utime(stale, (now, now))                  # the laundering: fresh mtime, old events
    os.utime(active, (now - 86_400, now - 86_400))
    assert _default_db(tmp_path) == str(active)

    # a FUTURE-dated *_at_millis (a trust grant's expires_at_millis is granted+7d — a schedule,
    # not activity) must not crown the dead store (review catch F1)
    w = PanelWriter(str(stale))
    w.emit_sync("cost_spent", {"role": "developer", "amount_usd": 0.01,
                               "spent_at_millis": int((now + 7 * 86_400) * 1000),
                               "correlation_id": "c"}, correlation_id="c")
    w.close()
    os.utime(stale, (1_000_000, 1_000_000))      # ancient mtime: only the future event could win
    assert _default_db(tmp_path) == str(active)


def _foreign_db(path):
    """The parallax.db shape: a healthy sqlite database that is not a devharness store."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()


def test_foreign_db_is_invisible_to_ranking_switch_and_discovery(tmp_path):
    """rev 0.4.13: the deployed notice named parallax.db (the MCP server's own db in var/) as the
    freshest store — its constantly-fresh mtime won the fallback ranking. Foreign files are never
    ranked, never listed, and never OPENED (opening runs migrate() into the foreign database)."""
    import os

    from devharness.panel.server import Panel, _default_db

    real = tmp_path / "projA.db"
    w = PanelWriter(str(real))
    w.close()
    foreign = tmp_path / "parallax.db"
    _foreign_db(foreign)
    now = time.time()
    os.utime(real, (now - 86_400, now - 86_400))
    os.utime(foreign, (now, now))               # foreign file has the freshest mtime — the live shape

    assert _default_db(tmp_path) == str(real)   # never a ranking candidate

    panel = Panel(str(real))
    try:
        # never offered as a project
        assert "parallax" not in {p["name"] for p in panel.session.discover_projects()}
        # never opened: the switch refuses through its clean path, foreign file unmodified
        before = foreign.read_bytes()
        res = panel.switch(str(foreign))
        assert res["ok"] is False and "not a devharness event store" in res["error"]
        assert foreign.read_bytes() == before
        # a new_project name-colliding with the foreign file is refused, not migrated
        res = panel.new_project("parallax", str(tmp_path / "repo"))
        assert res["ok"] is False and "not a devharness event store" in res["error"]
        assert foreign.read_bytes() == before
    finally:
        panel.writer.close()


def test_startup_notice_flags_a_stale_env_override(tmp_path, monkeypatch):
    """rev 0.4.5: a leftover DEVHARNESS_DB silently reopening an old store (live-hit minutes after
    the rev-0.4.4 default fix — the fix worked, the stale shell env overrode it). The panel now
    warns when the env-named store is NOT the most recently active one; a deliberate env pin of the
    freshest store (the VPS case) stays quiet, and no env means no notice."""
    import os

    from devharness.panel import server as pserver

    old = tmp_path / "devharness.db"
    new = tmp_path / "sample.db"
    # rev 0.4.13: candidates must be REAL stores (an empty file now fails the is_event_store
    # gate by design); a fresh migrated store has an empty events table -> activity None -> the
    # mtime-ranking assertions below stay meaningful.
    for pth in (old, new):
        w = PanelWriter(str(pth))
        w.close()
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    monkeypatch.setattr(pserver, "_default_db", lambda root=None: str(new))

    notice = pserver._startup_notice(str(old), from_env=True)
    assert notice and "DEVHARNESS_DB" in notice and "sample.db" in notice
    assert pserver._startup_notice(str(new), from_env=True) is None   # env pins the freshest: quiet
    assert pserver._startup_notice(str(old), from_env=False) is None  # no env: the default chose


def test_resolve_auth_clears_a_stray_api_key_by_default(tmp_path, monkeypatch):
    """rev 0.4.6: the interactive-box default is subscription auth — a machine-level stray
    ANTHROPIC_API_KEY made the claude subprocess die with a bare exit-1 (a Node project drive). The TUI +
    run_* convention (clear stray keys) now applies unless a systemd credential bridged the key or
    the operator explicitly opts into API-key auth."""
    import os

    from devharness.panel.server import _resolve_auth

    def reset():
        for var in ("ANTHROPIC_API_KEY", "CREDENTIALS_DIRECTORY",
                    "DEVHARNESS_PANEL_APIKEY", "DEVHARNESS_PANEL_SUBSCRIPTION"):
            monkeypatch.delenv(var, raising=False)

    reset()  # default: stray key cleared
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-stray")
    _resolve_auth()
    assert "ANTHROPIC_API_KEY" not in os.environ

    reset()  # explicit API-key opt-in: kept
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-mine")
    monkeypatch.setenv("DEVHARNESS_PANEL_APIKEY", "1")
    _resolve_auth()
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-mine"

    reset()  # systemd credential (the VPS): bridged and kept, stray-clear does not apply
    (tmp_path / "anthropic-key").write_text("sk-bridged\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-stale-parent")
    _resolve_auth()
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-bridged"


def test_job_error_carries_the_subprocess_stderr(tmp_path):
    """rev 0.4.6: an SDK ProcessError's message says 'check stderr' — the job record must actually
    carry it, or the panel's error banner is a dead end."""
    db = str(tmp_path / "j.db")
    writer = PanelWriter(db)
    runner = BuildRunner(db, writer)

    class _ProcErr(Exception):
        stderr = "Invalid API key · please run /login"

    def boom(conn, bus, cancel):
        raise _ProcErr("Command failed with exit code 1")

    job = runner.submit("research", boom)
    for _ in range(50):
        if runner.busy_label is None:
            break
        time.sleep(0.05)
    j = runner.job(job)
    assert j["status"] == "error" and "Invalid API key" in j["error"]
    writer.close()


def test_new_project_takes_a_test_command(tmp_path):
    """rev 0.4.7: New-project hardcoded `python -m pytest -q` — the verifier ran pytest against the
    first non-Python panel project's Node repo ('no tests ran', exit 5) and rejected a healthy task.
    A supplied test command reaches the target; blank still defaults to pytest."""
    from devharness.panel.server import Panel

    panel = Panel(str(tmp_path / "seed.db"))
    try:
        r = panel.new_project("nodeproj", str(tmp_path / "nodeproj"), "node --test")
        assert r["ok"] and panel.session.test_command == ["node", "--test"]
        r = panel.new_project("pyproj", str(tmp_path / "pyproj"), "")
        assert r["ok"] and panel.session.test_command == ["python", "-m", "pytest", "-q"]
    finally:
        panel.writer.close()


def test_pending_question_display_carries_every_question_readably(tmp_path):
    """rev 0.4.12: the card rendered raw elicit JSON (the 0.4.10 full-text swap); `display` is the
    COMPLETE question readable — every divergence point, no JSON syntax. `text` stays raw."""
    from devharness.panel import state as pstate
    db = str(tmp_path / "q.db")
    writer = PanelWriter(db)
    conn = sqlite3.connect(db)
    writer.emit_sync("research_started", {"correlation_id": "c"}, correlation_id="c")
    payload = json.dumps({
        "assumed_objective": "build a URL shortener",
        "divergence_points": [{"question": "coarse parsing ok?", "signal": "four cases"},
                              {"question": "stderr monitored?", "signal": "2>&1"}],
    })
    writer.emit_sync("question_asked", {"question_id": "q0", "research_id": "r",
                                        "question_text": payload, "correlation_id": "c"},
                     correlation_id="c")
    pq = pstate.pending_question(conn)
    assert "coarse parsing ok?" in pq["display"] and "stderr monitored?" in pq["display"]
    assert "{" not in pq["display"]
    assert pq["text"] == payload  # raw stays for API compat
    writer.close()


def test_question_card_renders_display_with_prewrap():
    """rev 0.4.12 source-grep pin (the rev-0.4.1 pattern): the card must render the `display`
    chain and carry pre-wrap — default CSS collapses the formatter's newlines into one blob,
    which was the plan review's blocker."""
    from pathlib import Path
    html = (Path(__file__).resolve().parents[2]
            / "runtime" / "devharness" / "panel" / "static" / "index.html").read_text(encoding="utf-8")
    q_rule = html[html.index(".q {"):html.index(".q {") + 200]
    assert "pre-wrap" in q_rule
    assert "s.pending_question.display||s.pending_question.text||s.pending_question.readable" in html.replace(" ", "")


def test_progress_frame_line_shared_module():
    """rev 0.4.3: the TUI's progress rendering extracted for the panel — salient fields only,
    and the module must never grow a Textual import (the panel host may not have it)."""
    import inspect

    from devharness.console import progress

    assert "textual" not in inspect.getsource(progress)
    line = progress.frame_line("verifier_outcome", {"task_id": "t1", "passed": True,
                                                    "irrelevant": "x"})
    assert line == "verifier_outcome  task_id=t1  passed=True"
    assert progress.frame_line("cost_spent", None) == "cost_spent"
    assert "verifier_outcome" in progress.PROGRESS_EVENTS


def _serve(tmp_path):
    db = str(tmp_path / "http.db")
    panel = Panel(db)
    srv = PanelServer(("127.0.0.1", 0), panel)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    return srv, port


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
        return r.status, json.load(r)


def _post(port, path, obj):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_http_state_and_inline_actions(tmp_path):
    srv, port = _serve(tmp_path)
    try:
        code, state = _get(port, "/state")
        assert code == 200 and state["next_hint"].startswith("set a build target")
        assert state["event_count"] == 0
        # set a build target -> creates the repo, emits build_target_set
        tgt = str(tmp_path / "proj")
        code, res = _post(port, "/target/set", {"value": f"{tgt} | python -m pytest -q"})
        assert code == 200 and res["ok"] and res["target_path"] == tgt
        code, state = _get(port, "/state")
        assert state["target_path"] == tgt and state["event_count"] == 1  # the build_target_set event
        # a typed action error surfaces as a clean 4xx, not a crash
        code, res = _post(port, "/spec/sign", {})
        assert code == 400 and "no unsigned spec" in res["error"]
        # unknown route -> 404
        code, res = _post(port, "/nope", {})
        assert code == 404
        # /events rows carry the rendered line: bare type for non-progress events, salient
        # payload fields for progress events (rev 0.4.3)
        code, ev = _get(port, "/events?after=0")
        assert code == 200 and ev["events"][0]["line"] == "build_target_set"
        srv.panel.writer.emit_sync("question_asked", {"question_id": "q1", "research_id": "r1",
                                   "question_text": "scope?", "correlation_id": "c"},
                                   correlation_id="c")
        code, ev = _get(port, "/events?after=1")
        assert "question_text=scope?" in ev["events"][0]["line"]
    finally:
        srv.shutdown()
        srv.panel.writer.close()


def test_http_build_step_is_single_flight_over_http(tmp_path):
    """Two rapid build POSTs: one is accepted (202), a concurrent one gets 409 — the guard holds over
    the HTTP surface, so two browser taps can't start two writers."""
    srv, port = _serve(tmp_path)
    try:
        # /plan with no correlation still claims the slot then errors in-job; fire two fast.
        codes = []
        results = []

        def fire():
            c, r = _post(port, "/plan", {})
            codes.append(c)
            results.append(r)

        # hold the slot with a blocking build via the runner directly, then a POST must 409
        release = threading.Event()
        srv.panel.runner.submit("dispatch", lambda c, b, x: release.wait(timeout=5))
        time.sleep(0.1)
        code, res = _post(port, "/plan", {})
        assert code == 409, f"expected busy 409, got {code} {res}"
        release.set()
    finally:
        srv.shutdown()
        srv.panel.writer.close()


# --- rev 0.4.15: the CSRF/DNS-rebinding request gate -------------------------------------------


def _request(port, path, *, method="GET", headers=None, data=None):
    """A request with explicit headers (urllib skips its auto-Host when one is supplied)."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e), dict(e.headers)


def _raw_http(port, request_bytes):
    """A raw-socket request, for header shapes urllib cannot produce (no Host / duplicate Host)."""
    import socket

    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(request_bytes)
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    return data


def test_gate_hostile_origin_post_403_and_action_not_run(tmp_path):
    """A cross-site POST (attacker Origin) is refused AND has no effect — the drive-by page and the
    enctype=text/plain form-smuggling path both arrive with the attacker's Origin."""
    srv, port = _serve(tmp_path)
    try:
        tgt = str(tmp_path / "proj")
        body = json.dumps({"value": f"{tgt} | python -m pytest -q"}).encode()
        code, res, _ = _request(port, "/target/set", method="POST", data=body,
                                headers={"Content-Type": "application/json",
                                         "Origin": "https://evil.example"})
        assert code == 403 and "Origin" in res["error"]
        code, state = _get(port, "/state")
        assert state["event_count"] == 0  # the action never ran
    finally:
        srv.shutdown()
        srv.panel.writer.close()


def test_gate_loopback_and_absent_origin_posts_pass(tmp_path):
    """The panel UI (loopback Origin) and curl/ssh scripts (no Origin) both reach the handler."""
    srv, port = _serve(tmp_path)
    try:
        # loopback Origin: reaches the action layer (400 from the action, not 403 from the gate)
        code, res, _ = _request(port, "/spec/sign", method="POST", data=b"{}",
                                headers={"Content-Type": "application/json",
                                         "Origin": f"http://127.0.0.1:{port}"})
        assert code == 400 and "no unsigned spec" in res["error"]
        # no Origin at all (the _post helper): same
        code, res = _post(port, "/spec/sign", {})
        assert code == 400 and "no unsigned spec" in res["error"]
    finally:
        srv.shutdown()
        srv.panel.writer.close()


def test_gate_null_origin_post_403(tmp_path):
    """Origin: null (sandboxed iframe) fails the present-must-match rule."""
    srv, port = _serve(tmp_path)
    try:
        code, res, _ = _request(port, "/spec/sign", method="POST", data=b"{}",
                                headers={"Content-Type": "application/json", "Origin": "null"})
        assert code == 403 and "Origin" in res["error"]
    finally:
        srv.shutdown()
        srv.panel.writer.close()


def test_gate_rebound_host_403_on_post_and_get(tmp_path):
    """DNS rebinding presents a non-loopback Host on a socket that reaches us — refused on writes
    AND reads (reads leak LLM/spec/db-path text; CORS never applies to a same-origin rebind)."""
    srv, port = _serve(tmp_path)
    try:
        code, res, _ = _request(port, "/state", headers={"Host": "attacker.example"})
        assert code == 403 and "Host" in res["error"]
        code, res, _ = _request(port, "/spec/sign", method="POST", data=b"{}",
                                headers={"Content-Type": "application/json",
                                         "Host": "attacker.example"})
        assert code == 403 and "Host" in res["error"]
    finally:
        srv.shutdown()
        srv.panel.writer.close()


def test_gate_public_host_env_admits(tmp_path, monkeypatch):
    """DEVHARNESS_PANEL_PUBLIC_HOST admits the proxied domain: exact, mixed-case (RFC 9110 hosts are
    case-insensitive), and a :port-carrying value for non-443 deploys; https Origin passes POSTs."""
    srv, port = _serve(tmp_path)
    try:
        monkeypatch.setenv("DEVHARNESS_PANEL_PUBLIC_HOST", "your-host.example.com")
        code, _, _ = _request(port, "/state", headers={"Host": "your-host.example.com"})
        assert code == 200
        code, _, _ = _request(port, "/state", headers={"Host": "YOUR-HOST.EXAMPLE.COM"})
        assert code == 200
        code, res, _ = _request(port, "/spec/sign", method="POST", data=b"{}",
                                headers={"Content-Type": "application/json",
                                         "Host": "your-host.example.com",
                                         "Origin": "https://your-host.example.com"})
        assert code == 400 and "no unsigned spec" in res["error"]  # through the gate
        monkeypatch.setenv("DEVHARNESS_PANEL_PUBLIC_HOST", "your-host.example.com:8443")
        code, _, _ = _request(port, "/state", headers={"Host": "your-host.example.com:8443"})
        assert code == 200
        code, _, _ = _request(port, "/state", headers={"Host": "your-host.example.com"})
        assert code == 403  # portless Host no longer matches the port-carrying config
    finally:
        srv.shutdown()
        srv.panel.writer.close()


def test_gate_absent_and_duplicate_host_403(tmp_path):
    """Fail-closed parsing edges: an HTTP/1.0 request with no Host, and a duplicate Host
    (headers.get silently returns the first) — both refused."""
    srv, port = _serve(tmp_path)
    try:
        raw = _raw_http(port, b"GET /state HTTP/1.0\r\n\r\n")
        assert raw.split(b"\r\n", 1)[0].endswith(b"403 Forbidden")
        raw = _raw_http(port, b"GET /state HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                              b"Host: 127.0.0.1\r\nConnection: close\r\n\r\n")
        assert raw.split(b"\r\n", 1)[0].endswith(b"403 Forbidden")
    finally:
        srv.shutdown()
        srv.panel.writer.close()


def test_gate_ipv6_loopback_admits(tmp_path):
    """[::1]:port is loopback too — a v6-bound deploy must not 403 with no escape."""
    srv, port = _serve(tmp_path)
    try:
        code, _, _ = _request(port, "/state", headers={"Host": f"[::1]:{port}"})
        assert code == 200
    finally:
        srv.shutdown()
        srv.panel.writer.close()


def test_no_cors_wildcard_on_responses(tmp_path):
    """rev 0.4.15 drops Access-Control-Allow-Origin: * from BOTH emission sites (_send_json + _diag)."""
    srv, port = _serve(tmp_path)
    try:
        _, _, headers = _request(port, "/state")
        assert "Access-Control-Allow-Origin" not in headers
        req = urllib.request.Request(f"http://127.0.0.1:{port}/diag")
        with urllib.request.urlopen(req) as r:
            assert "Access-Control-Allow-Origin" not in dict(r.headers)
    finally:
        srv.shutdown()
        srv.panel.writer.close()
