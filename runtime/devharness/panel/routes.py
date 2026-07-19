"""HTTP routing for the panel — GET reads + POST actions over the console action layer.

Every POST maps 1:1 onto a ``Console*`` action (the same ``emit_sync`` single-writer path the TUI
uses). Inline actions (answer / sign / reject / integrate / target / assemble) run under the writer
lock on the writer connection — the web analog of the TUI running inline actions on its one main
connection. Heavy LLM steps (research / plan / dispatch / certify) are handed to the ``BuildRunner``
and return ``202 {job_id}``; their progress streams to the browser over the sidecar SSE, and the job
record is polled at ``/job/{id}``. Reads (``/state`` etc.) open their own connection — never the
writer's — so they never contend with a build.
"""

import json
import os
import sqlite3
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

_STATIC = Path(__file__).parent / "static"

# Hosts an un-proxied client may legitimately present (rev 0.4.15 request gate).
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _host_of(authority: str) -> str:
    """The host portion of a Host-header/authority value, lowercased (``[::1]:8090`` → ``::1``)."""
    v = authority.strip().lower()
    if v.startswith("["):
        return v.partition("]")[0][1:]
    return v.partition(":")[0]

from devharness.console.assemble import ConsoleAssemble
from devharness.console.developer import ConsoleDeveloper, live_parallax_client, run_retro_drain
from devharness.console.director import ConsoleDirector
from devharness.console.progress import PROGRESS_EVENTS, frame_line
from devharness.console.research import ConsoleResearch
from devharness.console.review import ConsoleReview
from devharness.console.signoff import ConsoleSignoff
from devharness.models import model_for_tier
from devharness.panel import state as pstate
from devharness.panel.worker import BusyError, _StepCancelled


class PanelHandler(BaseHTTPRequestHandler):
    server_version = "devharness-panel/1"

    # --- plumbing ---

    @property
    def panel(self):
        return self.server.panel  # type: ignore[attr-defined]

    def log_message(self, *args):  # quiet the default stderr access log
        pass

    def _send_json(self, code: int, obj) -> None:
        # No Access-Control-Allow-Origin: the UI is served same-origin by the panel itself; a CORS
        # wildcard only ever served cross-origin readers of /state, /diag, /events, /cost
        # (rev 0.4.15 — removed with the request gate below).
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _gate_refusal(self) -> str | None:
        """CSRF/DNS-rebinding gate (rev 0.4.15) — a refusal reason, or None to admit.

        Every request (GET included — reads leak LLM/spec/db-path text, and a DNS-rebound hostname
        resolving to 127.0.0.1 is SAME-origin, so CORS never applies; only Host validation blocks
        it) must present a Host that is loopback or ``DEVHARNESS_PANEL_PUBLIC_HOST`` (the reverse
        proxy's domain, which MUST forward the original Host — Caddy's default does). Absent or
        duplicate Host fails closed. POSTs additionally: an Origin header, when present, must be
        loopback or ``https://<public-host>`` — this kills drive-by pages (their Origin is the
        attacker's, including the ``enctype=text/plain`` form-smuggling path) while keeping curl and
        the loopback ssh scripts (no Origin) working. The gate is CSRF/rebinding protection only:
        same-box processes still reach the loopback bind unauthenticated (authentication is the
        reverse proxy's job)."""
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1:
            return "missing or duplicate Host header"
        host = hosts[0].strip()
        public = (os.environ.get("DEVHARNESS_PANEL_PUBLIC_HOST") or "").strip()
        if not (_host_of(host) in _LOOPBACK_HOSTS
                or (public and host.lower() == public.lower())):
            return (f"Host {host!r} is neither loopback nor DEVHARNESS_PANEL_PUBLIC_HOST"
                    " — cross-site or DNS-rebound request refused")
        if self.command == "POST":
            origin = self.headers.get("Origin")
            if origin is not None:
                o = origin.strip().lower()
                authority = o.partition("://")[2]
                if not ((o.startswith(("http://", "https://"))
                         and _host_of(authority) in _LOOPBACK_HOSTS)
                        or (public and o == f"https://{public.lower()}")):
                    return (f"Origin {origin!r} is neither loopback nor the configured public host"
                            " — cross-site POST refused")
        return None

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}

    def _read_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.panel.db_path)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # --- GET ---

    def _send_html(self, name: str) -> None:
        f = _STATIC / name
        if not f.is_file():
            return self._send_json(404, {"error": f"no static {name}"})
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        refusal = self._gate_refusal()
        if refusal:
            return self._send_json(403, {"error": refusal})
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                return self._send_html("index.html")
            if path == "/events":
                after = int((parse_qs(parsed.query).get("after") or ["0"])[0])
                return self._events(after)
            if path == "/state":
                return self._state()
            if path == "/question":
                conn = self._read_conn()
                try:
                    return self._send_json(200, pstate.pending_question(conn) or {})
                finally:
                    conn.close()
            if path.startswith("/spec/review/"):
                spec_id = unquote(path[len("/spec/review/"):])
                conn = self._read_conn()
                try:
                    return self._send_json(200, ConsoleSignoff(conn, self.panel.writer).review(spec_id))
                finally:
                    conn.close()
            if path == "/projects":
                return self._send_json(200, {"projects": self.panel.session.discover_projects()})
            if path.startswith("/job/"):
                job = self.panel.runner.job(path[len("/job/"):])
                return self._send_json(200 if job else 404, job or {"error": "no such job"})
            if path == "/cost":
                return self._cost()
            if path == "/diag":
                return self._diag()
            return self._send_json(404, {"error": f"no route {path}"})
        except Exception as exc:  # noqa: BLE001 — surface as JSON, never 500-crash the thread
            return self._send_json(400, {"error": f"{type(exc).__name__}: {exc}"})

    def _state(self):
        conn = self._read_conn()
        try:
            s = self.panel.session
            snap = pstate.snapshot(conn, target_path=s.target_path, test_command=s.test_command,
                                   busy_label=self.panel.runner.busy_label,
                                   busy_job=self.panel.runner.busy_job)
            snap["db_path"] = self.panel.db_path
            # when real work last happened in this store (newest *_at_millis in recent events) —
            # the UI labels a stale store's age so old data is identifiable on sight. NOT file
            # mtime: a WAL checkpoint on mere open/close bumps that with zero events written.
            snap["store_activity_millis"] = pstate.last_activity_millis(conn)
            snap["notice"] = self.panel.notice  # startup warning (e.g. stale DEVHARNESS_DB override)
            jobs = self.panel.runner.jobs()
            snap["last_job"] = jobs[-1] if jobs else None  # UI raises an error banner on this
            return self._send_json(200, snap)
        finally:
            conn.close()

    def _events(self, after: int):
        """Progress tail — new events since ``after`` (the panel is self-contained; the UI polls this
        instead of needing the sidecar SSE). Returns at most 500 rows. ``line`` carries the TUI's
        salient-field rendering for progress events (rev 0.4.3), else the bare type."""
        conn = self._read_conn()
        try:
            rows = []
            for s, t, p in conn.execute(
                    "SELECT seq, event_type, payload FROM events WHERE seq > ? "
                    "ORDER BY seq LIMIT 500", (after,)):
                payload = json.loads(p) if p else {}
                rows.append({"seq": s, "event_type": t, "payload": payload,
                             "line": frame_line(t, payload) if t in PROGRESS_EVENTS else t})
            return self._send_json(200, {"events": rows})
        finally:
            conn.close()

    def _diag(self):
        """A paste-ready diagnostic bundle for sharing with the assistant: state + pending question +
        every job's status/error (the failure causes that aren't on screen) + recent events read
        straight from the store (so they're deduplicated, unlike the live progress log)."""
        conn = self._read_conn()
        try:
            s = self.panel.session
            snap = pstate.snapshot(conn, target_path=s.target_path, test_command=s.test_command,
                                   busy_label=self.panel.runner.busy_label,
                                   busy_job=self.panel.runner.busy_job)
            lines = ["=== devharness panel diagnostics ===",
                     f"store: {self.panel.db_path}",
                     f"next: {snap['next_hint']}",
                     f"busy: {snap['busy']}   events: {snap['event_count']}   "
                     f"cost: ${snap['cost_total_usd']}   target: {snap['target_path']}"]
            if snap.get("pending_question"):
                lines.append(f"pending question: {snap['pending_question'].get('readable', '')}")
            lines.append("")
            # live invariant monitor (rev 0.3.87): surface any behavioral-invariant breaches up front
            iv = conn.execute(
                "SELECT payload FROM events WHERE event_type='invariant_violated' ORDER BY seq DESC LIMIT 10"
            ).fetchall()
            lines.append(f"invariant violations: {len(iv)}")
            for (payload,) in iv:
                d = json.loads(payload)
                tid = f" [{d.get('task_id')}]" if d.get("task_id") else ""
                lines.append(f"  ⚠ Inv {d.get('invariant_number')}: {d.get('property')}{tid} — {d.get('detail', '')}")
            # loop fault-injection (rev 0.3.88): how many injected-fault probes ran + any handling regression
            lf_runs = conn.execute("SELECT COUNT(*) FROM events WHERE event_type='loop_fault_run'").fetchone()[0]
            lf_reg = conn.execute("SELECT COUNT(*) FROM events WHERE event_type='fault_handling_regression'").fetchone()[0]
            lines.append(f"loop faults: {lf_runs} run, {lf_reg} regressions")
            lines.append("")
            lines.append("jobs (label · status · error):")
            jobs = self.panel.runner.jobs()
            if not jobs:
                lines.append("  (none this session)")
            for j in jobs:
                err = f" — {j['error']}" if j.get("error") else ""
                lines.append(f"  {j['id']} {j['label']}: {j['status']}{err}")
            lines.append("")
            lines.append("recent events (from the store, deduplicated):")
            rows = conn.execute("SELECT seq, event_type FROM events ORDER BY seq DESC LIMIT 40").fetchall()
            for seq, et in reversed(rows):
                lines.append(f"  #{seq} {et}")
            body = "\n".join(lines).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            conn.close()

    def _cost(self):
        conn = self._read_conn()
        try:
            rows = [{"role": r, "spent_usd": v} for r, v in conn.execute(
                "SELECT role, spent_usd FROM proj_cost ORDER BY spent_usd DESC")]
            total = pstate.grand_total_cost(conn)
            return self._send_json(200, {"by_role": rows, "total_usd": round(total, 4)})
        finally:
            conn.close()

    # --- POST ---

    def do_POST(self):  # noqa: N802
        refusal = self._gate_refusal()
        if refusal:
            return self._send_json(403, {"error": refusal})
        path = urlparse(self.path).path
        body = self._body()
        try:
            handler = self._POST_ROUTES.get(path)
            if handler is None:
                return self._send_json(404, {"error": f"no route {path}"})
            return handler(self, body)
        except BusyError as exc:
            return self._send_json(409, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 — action-layer errors are operational; surface them
            return self._send_json(400, {"error": f"{type(exc).__name__}: {exc}"})

    # inline actions (run under the writer lock, on the writer connection) ---------------------

    def _inline(self, fn):
        """Run an action to completion under the single-writer lock and return its result."""
        w = self.panel.writer
        with w.lock:
            return fn(w.conn, w)

    def post_research_answer(self, body):
        answer = (body.get("answer") or "").strip()
        if not answer:
            return self._send_json(400, {"error": "answer is required"})

        def act(conn, w):
            qid = pstate.latest_unanswered_question(conn)
            if not qid:
                raise ValueError("no pending research question")
            return ConsoleResearch(conn, w).submit_answer(qid, answer)
        return self._send_json(200, {"question_id": self._inline(act)})

    def post_spec_sign(self, body):
        def act(conn, w):
            sid = body.get("spec_id") or pstate._latest_unsigned_spec(conn)
            if not sid:
                raise ValueError("no unsigned spec to sign")
            return ConsoleSignoff(conn, w).sign(sid)
        return self._send_json(200, {"spec_id": self._inline(act)})

    def post_spec_reject(self, body):
        reason = (body.get("reason") or "").strip()

        def act(conn, w):
            sid = body.get("spec_id") or pstate._latest_unsigned_spec(conn)
            if not sid:
                raise ValueError("no drafted spec to reject")
            return ConsoleSignoff(conn, w).reject(sid, reason)
        return self._send_json(200, {"spec_id": self._inline(act)})

    def post_integrate(self, body):
        task_id = body.get("task_id")
        if not task_id:
            return self._send_json(400, {"error": "task_id is required"})
        result = self._inline(lambda conn, w: ConsoleReview(conn, w).integrate(task_id))
        return self._send_json(200, {"result": result})

    def post_assemble(self, body):
        # assemble is a fast git merge (the TUI runs it inline, not as a worker) — run under the lock.
        cid = body.get("correlation_id")

        def act(conn, w):
            c = cid or pstate.latest_correlation(conn)
            if not c:
                raise ValueError("no correlation — plan/build first")
            base = self.panel.session.target_path
            kwargs = {"base_path": base} if base else {}
            return ConsoleAssemble(conn, w, **kwargs).assemble(c)
        return self._send_json(200, {"result": self._inline(act)})

    def post_target_set(self, body):
        value = body.get("value") or ""
        result = self.panel.session.set_target(value, self.panel.writer)
        return self._send_json(200 if result.get("ok") else 400, result)

    # heavy build steps (single-flight worker) ------------------------------------------------

    def post_research_start(self, body):
        seed = (body.get("seed") or "").strip()
        if not seed:
            return self._send_json(400, {"error": "seed is required"})
        job_id = self.panel.runner.submit("research", _research_step(seed))
        return self._send_json(202, {"job_id": job_id})

    def post_plan(self, body):
        def step(conn, bus, cancel):
            cid = body.get("correlation_id") or pstate.latest_correlation(conn)
            if not cid:
                raise ValueError("no correlation — run research first")
            return ConsoleDirector(conn, bus).plan(cid)
        return self._send_json(202, {"job_id": self.panel.runner.submit("director plan", step)})

    def post_dispatch(self, body):
        s = self.panel.session

        def step(conn, bus, cancel):
            cid = body.get("correlation_id") or pstate.latest_correlation(conn)
            if not cid:
                raise ValueError("no correlation — run research first")
            # Same refusal condition as the TUI + the hint machine: DEVHARNESS_TARGET_REPO counts as
            # a target (ConsoleDeveloper defaults base_path from it) — the prior session-only check
            # left the hint saying "build" while this route refused.
            if s.target_path is None and not os.environ.get("DEVHARNESS_TARGET_REPO"):
                raise ValueError("no build target set — set a target first")
            kwargs = {"base_path": s.target_path} if s.target_path is not None else {}
            if s.test_command is not None:
                kwargs["test_command"] = s.test_command
            # auto_retro: every panel-driven build feeds the §S7 spine post-build (rev 0.4.23)
            return ConsoleDeveloper(conn, bus, auto_retro=True, **kwargs).dispatch(cid, task_id=body.get("task_id"))
        return self._send_json(202, {"job_id": self.panel.runner.submit("developer dispatch", step)})

    def post_certify(self, body):
        task_id = body.get("task_id")
        if not task_id:
            return self._send_json(400, {"error": "task_id is required"})

        def step(conn, bus, cancel):
            return ConsoleReview(conn, bus).certify(task_id)
        return self._send_json(202, {"job_id": self.panel.runner.submit("certify", step)})

    def post_retro_run(self, body):
        # §S7 explicit retro drain (rev 0.4.23): T0 + T1 LLM residue over every unprocessed terminal +
        # signal in the connected store. The post-build auto-drain covers normal flow; this is the
        # backlog / parked-store trigger. Heavy (LLM spend per clean-residue terminal) -> BuildRunner
        # job; result via /job/{id}. A fermata-held store reports HELD, distinct from queue-empty.
        def step(conn, bus, cancel):
            return run_retro_drain(conn, bus)["summary"]
        return self._send_json(202, {"job_id": self.panel.runner.submit("retro run", step)})

    def post_cancel(self, body):
        job_id = body.get("job_id") or self.panel.runner.busy_job
        ok = self.panel.runner.cancel(job_id) if job_id else False
        return self._send_json(200, {"cancelled": ok, "job_id": job_id})

    # project management ----------------------------------------------------------------------

    def post_project_new(self, body):
        result = self.panel.new_project(body.get("name", ""), body.get("repo", ""),
                                        body.get("test_command", ""))
        seed = (body.get("seed") or "").strip()
        if result.get("ok") and seed:
            result["research_job"] = self.panel.runner.submit("research", _research_step(seed))
        return self._send_json(200 if result.get("ok") else 400, result)

    def post_project_switch(self, body):
        result = self.panel.switch(body.get("db_path", ""))
        return self._send_json(200 if result.get("ok") else 400, result)

    # bound after the class body (routes reference the methods below)
    _POST_ROUTES = {
        "/research/start": post_research_start,
        "/research/answer": post_research_answer,
        "/spec/sign": post_spec_sign,
        "/spec/reject": post_spec_reject,
        "/plan": post_plan,
        "/dispatch": post_dispatch,
        "/certify": post_certify,
        "/integrate": post_integrate,
        "/assemble": post_assemble,
        "/retro/run": post_retro_run,
        "/target/set": post_target_set,
        "/project/new": post_project_new,
        "/project/switch": post_project_switch,
        "/cancel": post_cancel,
    }


def _research_step(seed: str):
    """The research build-step closure — mirrors the TUI's ``_run_research`` (interactive: the worker
    parks in ``answer_fn`` polling for the ``question_answered`` event a ``/research/answer`` POST
    writes; research is advisory → its parallax runs on the cheaper T1 model)."""
    def step(conn, bus, cancel):
        import asyncio

        from devharness.roles.research import ResearchRole
        correlation_id = f"panel-research-{int(time.time())}"

        def answer_fn(question_id, _text):
            while not cancel.is_set():
                for (payload,) in conn.execute(
                        "SELECT payload FROM events WHERE event_type='question_answered'"):
                    rec = json.loads(payload)
                    if rec.get("question_id") == question_id:
                        return rec.get("answer_text", "")
                time.sleep(0.5)
            raise _StepCancelled()
        role = ResearchRole.spawn(conn=conn, correlation_id=correlation_id,
                                  parallax=live_parallax_client(model=model_for_tier("T1")),
                                  event_bus=bus, answer_fn=answer_fn)
        return asyncio.run(role.run(seed, correlation_id))
    return step
