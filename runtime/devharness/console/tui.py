"""Interactive operator console (TUI) — ``python -m devharness.console``.

A Textual app over the existing :class:`ConsoleApp` library: a live loop-state panel
plus keybindings that drive the *immediate* operator decisions (sign/reject/review a
spec, integrate a task, accept/reject a retro candidate, prune expired grants, enact an
approved gate-change). Every action calls a ``ConsoleApp`` method, so ``EventBus.emit_sync``
stays the sole writer and the console adds no write path of its own.

Thread model (load-bearing): the SQLite connection is opened with the default
``check_same_thread=True``, so it may only be touched on the UI thread. The live-state
follower therefore runs in a **daemon** thread that consumes the sidecar SSE stream and
does NO SQLite/widget access — per frame it asks the UI thread (``call_from_thread``) to
re-read ``loop_state()`` on the owning connection. If the sidecar is down (the common
solo-operator case — a refused connection raises immediately), it falls back to polling
``loop_state`` on a UI-thread timer. The daemon thread + a stop event mean a stalled
sidecar can never hang teardown.

The long-running LLM steps (research / director / developer / certify / OSS) are NOT here
— they run for minutes via role workers and need a separate worker-thread + progress
surface. This is the immediate-decision cut.
"""

import asyncio
import concurrent.futures
import json
import os
import shlex
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, RichLog, Static
from textual.worker import get_current_worker

from devharness.console.app import ConsoleApp
from devharness.console.developer import ConsoleDeveloper, live_parallax_client
from devharness.console.director import ConsoleDirector
from devharness.console.oss import ConsoleOss
from devharness.console.progress import PROGRESS_EVENTS, frame_line
from devharness.console.review import ConsoleReview
from devharness.console.sse import SSEFrame, StreamConsumer
from devharness.models import model_for_tier
from devharness.roles.research import full_question_text, readable_question_text
from devharness.worktree.contamination import foreign_scratch_correlations


def _fmt(obj) -> str:
    try:
        return json.dumps(obj, indent=2, default=str)
    except (TypeError, ValueError):
        return str(obj)


# Event types worth surfacing into the live progress panel — shared with the web panel (rev 0.4.3).
_PROGRESS_EVENTS = PROGRESS_EVENTS


class _StepCancelled(Exception):
    """Raised inside a build worker when the operator cancels (abandon, don't error)."""


class _ProxyBus:
    """The write path for a build-step worker thread.

    Every worker event emit is forwarded to the MAIN bus on the UI thread via
    ``call_from_thread``, so ``EventBus.emit_sync`` only ever runs on the single main
    connection on one thread — the event hash chain is never interleaved (a second
    writer connection would corrupt it; ``emit_sync`` is a non-atomic read-then-insert).
    Worker connections stay read-only for the chain; their non-event writes (artifacts,
    lock rows) are coordinated by WAL + busy_timeout.
    """

    def __init__(self, app: "ConsoleTUI") -> None:
        self._app = app

    def emit_sync(self, *args, **kwargs):
        return self._app.call_from_thread(self._app._console.writer.emit_sync, *args, **kwargs)


class _JoinPasteInput(Input):
    """An Input that joins a multi-line paste with single spaces instead of silently keeping only
    the first line (Textual's ``Input._on_paste`` inserts ``splitlines()[0]``) — a wrapped or
    multi-line seed/answer pasted into a prompt must never be truncated silently (this cut a live
    operator's project seed mid-sentence, twice).

    REWRITE-ONLY, deliberately: Textual dispatches ``_on_paste`` for EVERY class in the MRO (its
    no-super() handler design), so a subclass handler that inserts text does not replace Input's —
    both run, and every paste is inserted twice (the first version of this fix did exactly that,
    doubling a live operator's T value and project seed). This handler only rewrites ``event.text``
    to the joined form and lets Input's own handler do the single insertion."""

    def _on_paste(self, event) -> None:
        if event.text:
            lines = [ln for ln in (s.strip() for s in event.text.splitlines()) if ln]
            if len(lines) > 1:
                self.app.notify(f"paste: joined {len(lines)} lines", severity="warning")
            event.text = " ".join(lines)


class _ViewerModal(ModalScreen[None]):
    """Read-only scrollable viewer for long documents (spec bodies) — the log pane is for one-line
    action results, not documents (a spec dumped into the append-only RichLog scrolled the log away
    with no way back, live). Escape closes; arrows/PgUp/PgDn scroll (the frame takes focus). While
    open, app-level single-letter bindings can't fire — Textual truncates the binding chain at a
    modal screen, so q/v/W etc. are inert here (verified against the installed Textual source)."""

    CSS = """
    _ViewerModal { align: center middle; }
    _ViewerModal #frame { width: 90%; height: 90%; border: heavy white; padding: 0 1; }
    """
    BINDINGS = [("escape", "dismiss_viewer", "close")]

    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self._title = title
        self._text = text

    def compose(self) -> ComposeResult:
        # markup=False / pre-built Content: the body and title are STORE-DERIVED text — a spec whose
        # JSON contains ["packaging==24.0."] parsed as Textual markup and crashed the app at reflow,
        # outside any action handler (live, rev 0.3.62). border_title parses markup UNCONDITIONALLY
        # regardless of the widget's markup flag; an existing Content passes through unparsed.
        scroll = VerticalScroll(Static(self._text, markup=False), id="frame")
        scroll.border_title = Content(self._title)
        yield scroll

    def on_mount(self) -> None:
        self.query_one("#frame").focus()  # keyboard scrolling needs focus

    def action_dismiss_viewer(self) -> None:
        self.dismiss(None)


class _InputModal(ModalScreen[str | None]):
    """Prompt for a single line; dismiss with the text (Enter) or None (Escape)."""

    CSS = """
    _InputModal { align: center middle; }
    _InputModal #box { width: 70; height: auto; padding: 1; border: solid white; }
    _InputModal #box Label { width: 100%; }
    """
    BINDINGS = [("escape", "cancel", "cancel")]

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        # markup=False: prompts embed LLM question text (the A-prompt), and markup was silently
        # EATING literal bracket hints — the W prompt's "correlation_id [task_id]" rendered as
        # "correlation_id " until rev 0.3.62.
        yield Vertical(Label(self._prompt, markup=False), _JoinPasteInput(id="value"), id="box")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConsoleTUI(App):
    """The interactive operator console."""

    TITLE = "devharness operator console"
    CSS = """
    #state { border: heavy $primary; height: auto; padding: 0 1; }
    #progress { border: heavy $success; height: 2fr; }
    #log { border: heavy $warning; height: 1fr; }
    """
    BINDINGS = [
        ("r", "refresh", "refresh"),
        ("v", "review_spec", "review spec"),
        ("s", "sign_spec", "sign spec"),
        ("x", "reject_spec", "reject spec"),
        ("i", "integrate", "integrate"),
        ("c", "list_candidates", "candidates"),
        ("a", "accept_candidate", "accept"),
        ("j", "reject_candidate", "reject cand"),
        ("p", "list_expired", "grants"),
        ("k", "prune", "prune"),
        ("g", "list_gate_changes", "gate-changes"),
        ("e", "enact_gate_change", "enact"),
        ("$", "list_cost", "cost"),
        # Shift+letter = the long-running LLM build steps (run in a thread worker).
        ("R", "research", "research"),
        ("A", "answer", "answer"),
        ("D", "director_plan", "plan"),
        ("W", "developer_dispatch", "dispatch"),
        ("C", "certify", "certify"),
        ("M", "assemble", "assemble"),
        ("O", "oss_run", "oss"),
        ("T", "set_target", "set target"),
        ("P", "switch_project", "switch project"),
        ("N", "new_project", "new project"),
        ("ctrl+x", "cancel_step", "cancel step"),
        ("q", "quit", "quit"),
    ]

    def __init__(self, *, console: ConsoleApp | None = None, consumer_factory=None) -> None:
        super().__init__()
        # The connection is owned by this (UI) thread; never read it off-thread.
        self._console = console or ConsoleApp().connect()
        self._consumer_factory = consumer_factory or (lambda: StreamConsumer(timeout=5.0))
        self._stop = threading.Event()
        self._follow_thread: threading.Thread | None = None
        self._poll_timer = None
        self._poll_seq = 0  # event-log cursor for the no-sidecar progress fallback
        self._busy: str | None = None  # the running build step, if any (build-vs-build guard)
        self._current_role = "idle"  # the last role emitted to proj_role_state (dashboard tile, rev 0.3.79)
        self._active_worker = None  # the running build worker (for best-effort cancel)
        self._target_path: str | None = None  # the project repo the developer builds into (T action)
        self._test_command: list[str] | None = None  # the verifier's test command for that project
        self._developer_factory = ConsoleDeveloper  # test seam: the developer-surface constructor

    # --- lifecycle ---

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="state", markup=False)  # renders store text (hints/reasons/questions) — rev 0.3.62
        yield RichLog(id="progress", highlight=False, markup=False, wrap=True)
        yield RichLog(id="log", highlight=False, markup=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#state", Static).border_title = "state"
        self.query_one("#progress", RichLog).border_title = "progress · build events"
        self.query_one("#log", RichLog).border_title = "log · action results"
        if self._console.store_created:
            # A brand-new store is legitimate for a new project but contamination-shaped for
            # anything else (a mistyped/relative DEVHARNESS_DB lands here) — announce, never
            # silent (rev 0.3.63; the store-side sibling of the rev-0.3.61 target warning).
            self._log(f"⚠ created NEW EMPTY event store at {self._console.db_path} — "
                      "starting a new project? if not, quit (q) and check DEVHARNESS_DB")
        self._restore_target()
        self._refresh()
        self._log("keys: r refresh · v/s/x spec · i integrate · c/a/j candidates · "
                  "p/k prune · g/e gate-change · $ cost · q quit")
        self._log("build (Shift): T target · R research · A answer · D plan · W dispatch · "
                  "C certify · M assemble · O oss · P switch-project · N new-project · ctrl+x cancel")
        self._follow_thread = threading.Thread(target=self._follow_loop, daemon=True)
        self._follow_thread.start()

    def on_unmount(self) -> None:
        self._stop.set()

    # --- live state (UI thread reads SQLite; the follower thread never does) ---

    def _follow_loop(self) -> None:
        # call_from_thread against a stopped app raises RuntimeError ("event loop is
        # closed") or, mid-teardown, concurrent.futures.CancelledError — guard both so a
        # shutdown race unwinds the daemon thread silently instead of printing a traceback.
        _gone = (RuntimeError, concurrent.futures.CancelledError)
        try:
            for frame in self._consumer_factory().frames():
                if self._stop.is_set():
                    return
                try:
                    self.call_from_thread(self._on_frame, frame)
                except _gone:
                    return  # the app is no longer running
        except Exception:
            if self._stop.is_set():
                return  # teardown, not a stream error
            # sidecar down / stream error -> poll loop_state on the UI thread instead
            try:
                self.call_from_thread(self._start_polling)
            except _gone:
                pass

    def _start_polling(self) -> None:
        # No sidecar: tail the event log ourselves so a running build still shows live
        # per-event progress in #progress, not just aggregate #state.
        if self._poll_timer is None:
            self._poll_seq = self._max_seq()
            self._poll_timer = self.set_interval(2.0, self._poll_events)

    def _max_seq(self) -> int:
        return self._console.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]

    def _poll_events(self) -> None:
        """UI thread: tail new event rows by seq and render build-progress lines (no sidecar)."""
        rows = self._console.conn.execute(
            "SELECT seq, event_type, payload FROM events WHERE seq > ? ORDER BY seq",
            (self._poll_seq,),
        ).fetchall()
        for seq, event_type, payload in rows:
            self._poll_seq = seq
            if event_type in _PROGRESS_EVENTS:
                frame = SSEFrame(seq=seq, event_type=event_type, replayed=False,
                                 payload=json.loads(payload) if payload else {})
                self.query_one("#progress", RichLog).write(self._frame_line(frame))
        self._refresh()

    # A running build step, mapped to the role doing the work — the console tracks liveness through
    # _busy (nothing emits role_transitioned, so the proj_role_state field is always (none), rev 0.3.77).
    _BUSY_ROLE = {"research": "research", "director plan": "director",
                  "developer dispatch": "developer", "certify": "reviewer", "oss": "developer",
                  "assemble": "integrate"}

    def _active_role(self, st) -> str:
        """The role currently doing work: the running build step's role while busy, else '(idle)'.
        Reads _busy (live + accurate), NOT proj_role_state — no code emits role_transitioned, so that
        projection is always (none); showing it made the panel read as 'nothing is happening' during a build."""
        if self._busy:
            return self._BUSY_ROLE.get(self._busy, self._busy)
        return st.active_role or "(idle)"

    def _refresh(self) -> None:
        st = self._console.loop_state()
        spec = (f"spec: signed {st.signed_spec_id} by {st.signed_by or '(unknown)'}"
                if st.spec_signed else "spec: (unsigned)")
        tasks = ", ".join(f"{s}={n}" for s, n in sorted(st.tasks_by_state.items())) or "(none)"
        target = f"\ntarget: {self._target_path}" if self._target_path else ""
        cid = self._latest_correlation()
        corr = f"\ncorrelation: {cid}" if cid else ""
        spent = self._grand_total_cost()
        cost = f"  ·  cost: ${spent:.2f} ($ for detail)" if spent > 0 else ""
        self.query_one("#state", Static).update(
            f"→ next: {self._next_hint()}\n"
            f"active role: {self._active_role(st)}\n{spec}{corr}\ntasks: {tasks}\n"
            f"events: {st.event_count}{target}{cost}"
        )

    # --- state-derived defaults + next-step guidance ---

    def _q1(self, sql, *args):
        row = self._console.conn.execute(sql, args).fetchone()
        return row[0] if row else None

    def _latest_spec(self):
        return self._q1("SELECT json_extract(payload,'$.spec_id') FROM events "
                        "WHERE event_type='spec_drafted' ORDER BY seq DESC LIMIT 1")

    def _latest_unsigned_spec(self):
        latest = self._latest_spec()
        return latest if latest and latest != self._console.loop_state().signed_spec_id else None

    def _latest_correlation(self):
        """The signed spec's correlation (what D/W act on); else the latest research's correlation."""
        sid = self._console.loop_state().signed_spec_id
        if sid:
            cid = self._q1("SELECT correlation_id FROM artifacts WHERE artifact_id=?", sid)
            if cid:
                return cid
        return self._q1("SELECT correlation_id FROM events WHERE event_type='research_started' "
                        "ORDER BY seq DESC LIMIT 1")

    def _question_correlation(self):
        """The correlation whose questions A answers: the latest research run while it is IN FLIGHT
        (started, no spec drafted yet), else the signed-spec correlation. The signed-spec preference
        (right for D/W) made a SECOND research correlation's interview invisible to A — live on the
        dependency_bump drive, the 0.3.68 confirmation question sat pending in the new
        correlation while A said "no unanswered question" and research blocked forever (rev 0.3.69).
        Once the run drafts its spec (or a new run starts), the scope moves on — an abandoned run's
        question stops hijacking the hint at the next drafted spec, the original orphan concern."""
        rcid = self._q1("SELECT correlation_id FROM events WHERE event_type='research_started' "
                        "ORDER BY seq DESC LIMIT 1")
        if rcid and not self._q1("SELECT artifact_id FROM artifacts WHERE artifact_type='spec' "
                                 "AND correlation_id=? LIMIT 1", rcid):
            return rcid
        return self._latest_correlation()

    def _latest_unanswered_question(self):
        # scoped to the question correlation — an orphaned question from an abandoned research run
        # must not hijack the hint / the A default, but a LIVE second-correlation interview must win.
        cid = self._question_correlation()
        if not cid:
            return None
        asked = [r[0] for r in self._console.conn.execute(
            "SELECT json_extract(payload,'$.question_id') FROM events "
            "WHERE event_type='question_asked' AND correlation_id=? ORDER BY seq", (cid,))]
        answered = {r[0] for r in self._console.conn.execute(
            "SELECT json_extract(payload,'$.question_id') FROM events "
            "WHERE event_type='question_answered' AND correlation_id=?", (cid,))}
        pending = [q for q in asked if q not in answered]
        return pending[-1] if pending else None

    def _pending_question_text(self, question_id):
        """The raw question_text for a pending question_id — restart-proof (a direct DB read, not log
        history). ORDER BY seq DESC LIMIT 1: a re-driven research run resets its round counter to 0, so
        question_id can collide across runs against the same correlation; the latest row wins."""
        return self._q1(
            "SELECT json_extract(payload,'$.question_text') FROM events "
            "WHERE event_type='question_asked' AND correlation_id=? "
            "AND json_extract(payload,'$.question_id')=? ORDER BY seq DESC LIMIT 1",
            self._question_correlation(), question_id,
        )

    def _plan_outcomes(self):
        """(task_ids, {task_id: latest_outcome}) for the current plan; None when there is no plan yet.
        Outcome is the LATEST terminal per task (a re-drive appends) — absent ⇒ not yet terminal."""
        cid = self._latest_correlation()
        pid = self._q1("SELECT json_extract(payload,'$.plan_id') FROM events "
                       "WHERE event_type='plan_drafted' AND correlation_id=? ORDER BY seq DESC LIMIT 1",
                       cid) if cid else None
        if not pid:
            return None
        row = self._console.conn.execute(
            "SELECT payload_json FROM artifacts WHERE artifact_id=?", (pid,)).fetchone()
        if not row:
            return None
        task_ids = [t.get("task_id") for t in json.loads(row[0]).get("tasks", [])]
        latest = {}
        for tid, outcome in self._console.conn.execute(
                "SELECT json_extract(payload,'$.task_id'), json_extract(payload,'$.outcome') "
                "FROM events WHERE event_type='terminal_outcome' ORDER BY seq"):
            if tid in task_ids:
                latest[tid] = outcome
        return task_ids, latest

    def _terminal_reason(self, task_id):
        """The latest terminal_outcome's reason (falling back to detail) for task_id, or ''."""
        return self._q1(
            "SELECT COALESCE(NULLIF(json_extract(payload,'$.reason'), ''), "
            "json_extract(payload,'$.detail')) FROM events "
            "WHERE event_type='terminal_outcome' AND json_extract(payload,'$.task_id')=? "
            "ORDER BY seq DESC LIMIT 1", task_id,
        ) or ""

    def _next_hint(self) -> str:
        if self._busy:
            # A research step BLOCKS on the operator's answer — the worker thread polls silently for
            # it, so a bare "running: research" reads as stuck (the live friction, rev 0.3.74). Surface
            # a pending question even while busy. Gated to "research" — the only step that asks
            # questions; a director/developer/oss step keeps the plain running line.
            if self._busy == "research":
                pending_qid = self._latest_unanswered_question()
                if pending_qid:
                    text = self._pending_question_text(pending_qid)
                    q = readable_question_text(text, max_len=120) if text else "the research question"
                    return f"A — answer (research is waiting): {q}"
            return f"running: {self._busy}  (ctrl+x to cancel)"
        pending_qid = self._latest_unanswered_question()
        if pending_qid:
            text = self._pending_question_text(pending_qid)
            if text:
                return f"A — answer: {readable_question_text(text, max_len=150)}"
            return "A — answer the research question"
        if self._latest_unsigned_spec():
            return "s — sign the drafted spec"
        if not self._console.loop_state().spec_signed:
            return "T — set a build target, then R — start research"
        outcomes = self._plan_outcomes()
        if outcomes is None:
            return "D — plan the signed spec"
        task_ids, latest = outcomes
        # a task that reached a non-completed terminal (rejected/aborted) blocks the plan
        # (proj_plan.current_state flips to 'blocked') — surface it BEFORE the pending-tasks
        # hint, so W's intentional advance-past-any-terminal behavior (rev 0.3.37, preserved
        # here on purpose — refusing to advance would reintroduce the infinite-hang it fixed)
        # never happens silently.
        blocked = [t for t in task_ids if latest.get(t) not in (None, "completed")]
        pending = [t for t in task_ids if t not in latest]
        if blocked:
            tid, outcome = blocked[0], latest[blocked[0]]
            reason = self._terminal_reason(tid)
            # Truncate for the HINT only (the full reason stays in the event log / progress pane) —
            # a scope_violation listing 9 files produced a 9-line wall that drowned the retry command.
            if len(reason) > 120:
                reason = reason[:120] + "…"
            note = f" ({reason})" if reason else ""
            # W's prompt is 'correlation_id [task_id]' (two space-separated tokens) — a lone task_id
            # gets parsed as the correlation_id instead, which is exactly the bug this caused live.
            cid = self._latest_correlation()
            retry = f"W, then type: {cid} {tid}"
            if pending:
                return (f"⚠ {tid} {outcome}{note} — needs operator review; "
                        f"W will SKIP PAST it to the next pending task ({len(pending)} left) "
                        f"— {retry} to retry it explicitly")
            return (f"⚠ {tid} {outcome}{note} — assemble blocked until every task completes; "
                    f"{retry} to retry it")
        if pending:
            if self._target_path is None and not os.environ.get("DEVHARNESS_TARGET_REPO"):
                return f"T — set a build target, then W — build  ({len(pending)} tasks)"
            return f"W — build the next task  ({len(pending)} left)"
        if self._q1("SELECT 1 FROM events WHERE event_type='project_assembled' AND correlation_id=?",
                     self._latest_correlation()):
            return "done — project assembled (all tasks built + merged)"
        return "M — assemble the project (merge into the target's main)"

    def _on_frame(self, frame) -> None:
        """UI thread: a new SSE frame — refresh state and surface build progress."""
        self._refresh()
        if getattr(frame, "event_type", None) in _PROGRESS_EVENTS:
            self.query_one("#progress", RichLog).write(self._frame_line(frame))

    @staticmethod
    def _frame_line(frame) -> str:
        return "  " + frame_line(frame.event_type, frame.payload)

    # --- action plumbing ---

    def _log(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)

    def _act(self, fn: Callable[[], object], ok: Callable[[object], str]) -> None:
        try:
            self._log(ok(fn()))
        except Exception as exc:  # surface the action's specific error, never crash the TUI
            self._log(f"ERROR: {type(exc).__name__}: {exc}")
        self._refresh()

    def _prompt(self, prompt: str, then: Callable[[str], None]) -> None:
        def _cb(value: str | None) -> None:
            if value is not None and value.strip():
                then(value.strip())
        self.push_screen(_InputModal(prompt), _cb)

    def _prompt_opt(self, prompt: str, then: Callable[[str], None]) -> None:
        """Like _prompt but Enter on a BLANK input still calls ``then("")`` (Escape cancels) — so the
        handler can fall back to a state-derived default. Lets the operator drive with just keypresses."""
        def _cb(value: str | None) -> None:
            if value is not None:
                then(value.strip())
        self.push_screen(_InputModal(prompt), _cb)

    # --- actions (immediate; pure emit_sync / SELECT, no LLM) ---

    def action_refresh(self) -> None:
        self._refresh()
        self._log("refreshed")

    def action_review_spec(self) -> None:
        self._prompt_opt("spec_id to review (blank = latest):", self._review_spec)

    def _review_spec(self, value: str) -> None:
        sid = value or self._latest_spec()
        try:
            body = self._console.signoff().review(sid)
        except Exception as exc:  # same error surface as _act: log it, never crash the TUI
            self._log(f"ERROR: {type(exc).__name__}: {exc}")
            self._refresh()
            return
        self._log(f"reviewing spec {sid} (Escape closes the viewer)")
        self.push_screen(_ViewerModal(f"spec {sid}", _fmt(body)))
        self._refresh()

    def action_sign_spec(self) -> None:
        self._prompt_opt("spec_id to sign (blank = latest unsigned):", lambda v: self._act(
            lambda: self._console.signoff().sign(v or self._latest_unsigned_spec()),
            lambda sid: f"signed {sid}"))

    def action_reject_spec(self) -> None:
        self._prompt("reject spec — 'spec_id reason':", self._reject_spec)

    def _reject_spec(self, value: str) -> None:
        parts = value.split(maxsplit=1)
        if len(parts) < 2:
            self._log("ERROR: expected 'spec_id reason'")
            return
        spec_id, reason = parts
        self._act(lambda: self._console.signoff().reject(spec_id, reason),
                  lambda sid: f"rejected {sid}")

    def action_integrate(self) -> None:
        self._prompt("task_id to integrate:", lambda v: self._act(
            lambda: self._console.review().integrate(v), lambda disp: f"integrate -> {disp}"))

    def _list_in_viewer(self, title: str, fetch) -> None:
        """Render a list action in the scrollable viewer — the v treatment (rev 0.3.72): a list
        dumped into the append-only log scrolls everything away with no way back (the same live
        defect the spec viewer fixed; c hit it first, p/g share the surface). An empty list stays
        a one-line log entry — no modal for nothing. Escape closes, then a/j/e as usual (app keys
        are inert while a modal is open)."""
        try:
            rows = fetch()
        except Exception as exc:  # same error surface as _act: log it, never crash the TUI
            self._log(f"ERROR: {type(exc).__name__}: {exc}")
            self._refresh()
            return
        if not rows:
            self._log(f"{title}: none")
            self._refresh()
            return
        self._log(f"{title}: {len(rows)} (Escape closes the viewer)")
        self.push_screen(_ViewerModal(title, _fmt(rows)))
        self._refresh()

    def action_list_candidates(self) -> None:
        self._list_in_viewer("retro candidates", lambda: self._console.task_decision().list_pending())

    def _grand_total_cost(self) -> float:
        """Total recorded LLM spend across all roles (proj_cost) — 0.0 if nothing spent (rev 0.3.81)."""
        row = self._console.conn.execute("SELECT COALESCE(SUM(spent_usd), 0) FROM proj_cost").fetchone()
        return float(row[0]) if row else 0.0

    def _cost_report(self):
        """A plain-text per-role·model + per-project + total LLM-spend report, or None if nothing
        spent. The empty-guard and TOTAL stay on proj_cost (one source, the accumulated projection —
        its sum equals the events' sum, handle_cost_spent being proj_cost's sole writer); the per-role
        listing splits by the model that billed each spend (rev 0.4.2 — cost_spent carries `model`;
        a pre-0.4.2 event without one renders as `—`), and per-project is reconstructed from the raw
        events (proj_cost collapses to per-role, but the events carry correlation_id)."""
        conn = self._console.conn
        roles = conn.execute("SELECT role, spent_usd FROM proj_cost ORDER BY spent_usd DESC").fetchall()
        if not roles:
            return None
        role_models = conn.execute(
            "SELECT json_extract(payload,'$.role'), COALESCE(json_extract(payload,'$.model'),''), "
            "SUM(json_extract(payload,'$.amount_usd')) "
            "FROM events WHERE event_type='cost_spent' GROUP BY 1, 2 ORDER BY 3 DESC"
        ).fetchall()
        projects = conn.execute(
            "SELECT json_extract(payload,'$.correlation_id'), SUM(json_extract(payload,'$.amount_usd')) "
            "FROM events WHERE event_type='cost_spent' GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
        total = sum(spent for _role, spent in roles)
        lines = ["Per role · model:"]
        lines += [f"  {role:<16} {(model or '—'):<18} ${spent:.4f}" for role, model, spent in role_models]
        lines += ["", "Per project (correlation):"]
        lines += [f"  {(cid or '(none)'):<32} ${spent:.4f}" for cid, spent in projects]
        lines += ["", f"TOTAL: ${total:.4f}"]
        return "\n".join(lines)

    def action_list_cost(self) -> None:
        text = self._cost_report()
        if text is None:
            self._log("cost: no LLM spend recorded yet")
            return
        self._log("cost (Escape closes the viewer)")
        self.push_screen(_ViewerModal("cost — LLM spend", text))

    def action_accept_candidate(self) -> None:
        self._prompt("accept — 'queue row_id':", self._accept_candidate)

    def _accept_candidate(self, value: str) -> None:
        parts = value.split()
        if len(parts) < 2 or not parts[1].isdigit():
            self._log("ERROR: expected 'queue row_id' (row_id numeric)")
            return
        queue, row_id = parts[0], int(parts[1])
        self._act(lambda: self._console.task_decision().accept(queue, row_id),
                  lambda r: f"accepted {queue} #{row_id} -> {r}")

    def action_reject_candidate(self) -> None:
        self._prompt("reject — 'queue row_id reason':", self._reject_candidate)

    def _reject_candidate(self, value: str) -> None:
        parts = value.split(maxsplit=2)
        if len(parts) < 3 or not parts[1].isdigit():
            self._log("ERROR: expected 'queue row_id reason' (row_id numeric)")
            return
        queue, row_id, reason = parts[0], int(parts[1]), parts[2]
        self._act(lambda: self._console.task_decision().reject(queue, row_id, reason),
                  lambda r: f"rejected {queue} #{row_id}")

    def action_list_expired(self) -> None:
        self._list_in_viewer("expired trust grants", lambda: self._console.prune().list_expired())

    def action_prune(self) -> None:
        self._prompt("prune expired grants — reason:", lambda v: self._act(
            lambda: self._console.prune().prune(v), lambda n: f"pruned {n} grant(s)"))

    def action_list_gate_changes(self) -> None:
        self._list_in_viewer("approved gate-changes",
                             lambda: self._console.enact_gate_change().list_approved())

    def action_enact_gate_change(self) -> None:
        self._prompt("gate-change row_id to enact:", self._enact_gate_change)

    def _enact_gate_change(self, value: str) -> None:
        if not value.isdigit():
            self._log("ERROR: expected a numeric row_id")
            return
        row_id = int(value)
        self._act(lambda: self._console.enact_gate_change().enact(row_id),
                  lambda r: f"enacted gate-change #{r}")

    # --- build steps (cut 2): long-running LLM actions, each in a thread worker ---

    def _ui(self, fn, *args) -> None:
        """Run fn on the UI thread from a worker; swallow the app-stopped race."""
        try:
            self.call_from_thread(fn, *args)
        except (RuntimeError, concurrent.futures.CancelledError):
            pass

    def _progress(self, text: str) -> None:
        self.query_one("#progress", RichLog).write(text)
        self._refresh()

    def _begin(self, label: str) -> bool:
        """UI thread: claim the single build slot. False if busy or the DB can't WAL."""
        if self._busy:
            self._log(f"busy: {self._busy} is running (ctrl+x to cancel)")
            return False
        if self._console.db_path in (":memory:", "", None):
            self._log("ERROR: build steps need a file-backed DEVHARNESS_DB (not :memory:)")
            return False
        self._busy = label
        self.sub_title = f"running: {label}"
        self._emit_role_transition(self._BUSY_ROLE.get(label, label))  # feed the dashboard role tile
        self._progress(f"▶ {label}…")
        return True

    def _emit_role_transition(self, to_role: str) -> None:
        """Feed proj_role_state — the dashboard's 'Active role & FSM state' tile — at each build-step
        boundary. Nothing else in the runtime emits role_transitioned (rev 0.3.79; the projection was
        a B0 stub with no writer). Console-local; the projection is a singleton so the correlation is
        provenance only. Telemetry-only — a failed emit never breaks the build step it brackets."""
        prev = getattr(self, "_current_role", "idle")
        if to_role == prev:
            return
        self._current_role = to_role
        try:
            self._console.writer.emit_sync(
                "role_transitioned", {"from_role": prev, "to_role": to_role}, correlation_id="console")
        except Exception:
            self._current_role = prev  # emit failed — don't desync the tracked role

    def _end(self) -> None:
        self._emit_role_transition("idle")
        self._busy = None
        self._active_worker = None
        self.sub_title = ""

    def action_cancel_step(self) -> None:
        if not self._busy or self._active_worker is None:
            self._log("no build step running")
            return
        self._log(f"cancelling {self._busy} — best-effort; the in-flight LLM run can't be "
                  "force-stopped, only abandoned")
        self._active_worker.cancel()

    def action_quit(self) -> None:
        # Quitting mid-build tears down the loop, so the developer's finally-block lock
        # release (an emit through the proxy) would fail and strand the write lock. Refuse.
        if self._busy:
            self._log(f"can't quit while {self._busy} is running (ctrl+x to abandon it first)")
            return
        self.exit()

    @work(thread=True, exit_on_error=False, group="build")
    def _run_step(self, label: str, fn: Callable[[sqlite3.Connection, _ProxyBus], object]) -> None:
        worker = get_current_worker()
        conn = None
        try:
            conn = sqlite3.connect(self._console.db_path)
            conn.execute("PRAGMA busy_timeout=5000")
            result = fn(conn, _ProxyBus(self))
            if not worker.is_cancelled:
                self._ui(self._progress, f"✔ {label}: {result}")
        except Exception as exc:  # noqa: BLE001 — surface, never crash the TUI
            if not worker.is_cancelled:
                self._ui(self._progress, f"✖ {label}: {type(exc).__name__}: {exc}")
        finally:
            if conn is not None:
                conn.close()
            self._ui(self._end)

    def _launch(self, label: str, fn) -> None:
        if self._begin(label):
            self._active_worker = self._run_step(label, fn)

    def action_director_plan(self) -> None:
        self._prompt_opt("director plan — correlation_id (blank = latest):", self._director_plan)

    def _director_plan(self, value: str) -> None:
        cid = value or self._latest_correlation()
        if not cid:
            self._log("no correlation — run research first (R)")
            return
        self._launch("director plan", lambda conn, bus: ConsoleDirector(conn, bus).plan(cid))

    def action_developer_dispatch(self) -> None:
        self._prompt_opt("developer dispatch — 'correlation_id [task_id]' (blank = latest):",
                         self._developer_dispatch)

    def _developer_dispatch(self, value: str) -> None:
        parts = value.split()
        cid = parts[0] if parts else self._latest_correlation()
        task_id = parts[1] if len(parts) > 1 else None  # None = dispatch the next pending task
        if not cid:
            self._log("no correlation — run research first (R)")
            return
        if self._target_path is None and not os.environ.get("DEVHARNESS_TARGET_REPO"):
            self._log("refused: no build target set — press T to set the project repo first "
                      "(so a build can't accidentally land inside devharness). "
                      "To build devharness itself, set T to its path.")
            return
        self._launch("developer dispatch",
                     lambda conn, bus: self._developer_surface(conn, bus).dispatch(cid, task_id=task_id))

    def _developer_surface(self, conn, bus):
        """ConsoleDeveloper scoped to the operator's set build target (base_path + test command), if any."""
        kwargs = {}
        if self._target_path is not None:
            kwargs["base_path"] = self._target_path
        if self._test_command is not None:
            kwargs["test_command"] = self._test_command
        return self._developer_factory(conn, bus, **kwargs)

    def action_set_target(self) -> None:
        self._prompt("build target — '<repo_path> | <test command>'  (e.g. ../proj | python -m pytest -q):",
                     self._set_target)

    # --- project switching (rev 0.3.75): drive a different store without quitting ---

    def _discover_projects(self) -> list[tuple[str, str, str]]:
        """(db_path, name, target) for every ``*.db`` store beside the current one — READ-ONLY, so
        listing never migrates/locks a sibling store (the review's catch: ConsoleApp.connect migrates
        = writes). A store that won't open / has no target shows ``(no target)``; never crashes."""
        cur = self._console.db_path
        if cur in (":memory:", "", None):
            return []
        from devharness.migrate import is_event_store

        out: list[tuple[str, str, str]] = []
        for db in sorted(Path(cur).parent.glob("*.db")):
            # rev 0.4.13: omit foreign sqlite files (positive not-a-store evidence only — a
            # transiently-unreadable REAL store keeps its row); panel parity in discover_projects.
            if is_event_store(db) is False:
                continue
            target = "(no target)"
            try:
                ro = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)  # file:///D:/… — Windows-safe
                try:
                    row = ro.execute(
                        "SELECT json_extract(payload,'$.target_path') FROM events "
                        "WHERE event_type='build_target_set' ORDER BY seq DESC LIMIT 1"
                    ).fetchone()
                    if row and row[0]:
                        target = row[0]
                finally:
                    ro.close()
            except sqlite3.Error:
                target = "(unreadable)"
            out.append((str(db), db.stem, target))
        return out

    def action_switch_project(self) -> None:
        if self._busy:
            self._log(f"can't switch while {self._busy} is running (ctrl+x to abandon it first)")
            return
        projects = self._discover_projects()
        if not projects:
            self._log("no other project stores found beside the current one (see N — new project)")
            return
        lines = [f"  {i + 1}. {name}  →  {target}" for i, (_p, name, target) in enumerate(projects)]
        listing = "switch project — type a number, or a full store path:\n" + "\n".join(lines)
        self._switch_choices = [p for (p, _n, _t) in projects]
        self._prompt(listing, self._switch_project_pick)

    def _switch_project_pick(self, value: str) -> None:
        choices = getattr(self, "_switch_choices", [])
        if value.isdigit() and 1 <= int(value) <= len(choices):
            self._switch_project(choices[int(value) - 1])
        elif value.endswith(".db") or "/" in value or "\\" in value:
            self._switch_project(value)
        else:
            self._log(f"no such choice: {value!r} (a list number or a .db path)")

    def _switch_project(self, db_path: str) -> None:
        """Reconnect the console to a different store on the UI thread — refused mid-build (the worker
        reads self._console.db_path LIVE, so a swap under it would corrupt; _busy forbids it). The state
        panel re-derives from the new store immediately; if polling is the live tail (no sidecar) it
        follows the new conn from its head. Sidecar limitation: the sidecar tails a FIXED store, so with
        one running the progress pane keeps showing the launch store's events until the sidecar restarts."""
        if self._busy:
            self._log("can't switch mid-build")
            return
        try:
            new_console = ConsoleApp(db_path=db_path).connect()
        except Exception as exc:  # a bad path / unmigratable store must not kill the console
            self._log(f"switch failed: {type(exc).__name__}: {exc}")
            return
        try:
            self._console.conn.close()
        except Exception:
            pass
        self._console = new_console
        self._poll_seq = self._max_seq()  # new store head — don't replay its whole log as progress
        self._target_path = None
        self._test_command = None
        if self._console.store_created:
            self._log(f"⚠ created NEW EMPTY event store at {self._console.db_path} — new project? "
                      "if not, this is a mistyped path")
        self._restore_target()
        self._log(f"switched to {Path(db_path).stem}")
        if self._poll_timer is None:
            self._log("note: a sidecar (if running) still tails the launch store; the state panel is "
                      "live, but the progress pane follows the launch store until the sidecar restarts")
        self._refresh()

    def action_new_project(self) -> None:
        if self._busy:
            self._log(f"can't start a new project while {self._busy} is running")
            return
        self._prompt("new project — 'name | repo_path | seed idea':", self._new_project)

    def _new_project(self, value: str) -> None:
        parts = [p.strip() for p in value.split("|")]
        if len(parts) < 3 or not all(parts[:3]):
            self._log("ERROR: expected 'name | repo_path | seed' (three | -separated fields)")
            return
        name, repo, seed = parts[0], parts[1], "|".join(parts[2:])  # a seed may contain '|'
        store = Path(self._console.db_path).parent / f"{name}.db"
        self._switch_project(str(store))  # creates + swaps to the new store (announces store_created)
        if Path(self._console.db_path).stem != name:  # the swap failed — don't proceed
            return
        self._set_target(f"{repo} | python -m pytest -q")
        if self._target_path is None:  # target set failed (bad repo) — don't start research
            self._log("new project: target not set, research not started — fix the repo path and press R")
            return
        self._start_research(seed)

    def _set_target(self, value: str) -> None:
        path, sep, cmd = value.partition("|")
        path = path.strip()
        if not path:
            self._log("target NOT set — give a repo path")
            return
        # Prepare the target on demand: create the dir, git-init, and give it a commit if missing
        # (a worktree needs a HEAD to branch from) — so setting a target is one keypress, no separate
        # mkdir/git-init command that can be missed or fail silently.
        problem = self._prepare_target(path)
        if problem:
            self._log(f"target NOT set — {problem}")
            return
        self._warn_foreign_branches(path)
        self._target_path = path
        self._test_command = shlex.split(cmd.strip(), posix=False) if (sep and cmd.strip()) else None
        # Persist the target in the event store (audit-only, no projection) so a console restart
        # restores it instead of forcing error-prone re-entry — a stale re-entered target once landed
        # an entire build in the WRONG project's repo. Correlation is the literal "console": T normally
        # precedes any research correlation, and the latest one would belong to a PRIOR run.
        self._console.writer.emit_sync(
            "build_target_set",
            {"target_path": self._target_path, "test_command": self._test_command or [],
             "correlation_id": "console"},
            correlation_id="console",
        )
        cmd_note = f"  ·  test = {' '.join(self._test_command)}" if self._test_command else ""
        self._log(f"build target = {self._target_path}{cmd_note}")
        self._refresh()

    def _restore_target(self) -> None:
        """Restore the store's latest T-set build target on launch (the event store is per-project, so
        this is project-scoped). Validates the path is still a git repo with a HEAD — a stale/deleted
        path is reported, NOT restored, and deliberately NOT re-created (_prepare_target would silently
        resurrect an empty repo at a stale location, which is contamination-shaped)."""
        row = self._console.conn.execute(
            "SELECT json_extract(payload,'$.target_path'), payload FROM events "
            "WHERE event_type='build_target_set' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if not row:
            self._warn_env_target()  # env-only targets never transit T/restore — check here
            return
        path = row[0]
        cmd = json.loads(row[1]).get("test_command") or []
        ok = Path(path).is_dir() and subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True
        ).returncode == 0
        if not ok:
            self._log(f"stale build target NOT restored: {path} (missing or not a git repo) — press T")
            self._warn_env_target()  # W would fall through to the env target — check it too
            return
        self._target_path = path
        self._test_command = list(cmd) if cmd else None  # [] round-trips to None (env/off semantics)
        cmd_note = f"  ·  test = {' '.join(self._test_command)}" if self._test_command else ""
        self._log(f"restored build target = {path}{cmd_note}")
        self._warn_foreign_branches(path)
        if os.environ.get("DEVHARNESS_TARGET_REPO"):
            self._log("note: restored target overrides DEVHARNESS_TARGET_REPO for this session")

    def _warn_env_target(self) -> None:
        env = os.environ.get("DEVHARNESS_TARGET_REPO")
        if env:
            self._warn_foreign_branches(env)

    def _warn_foreign_branches(self, path: str) -> None:
        """Contamination guard (rev 0.3.61): scratch branches whose correlation this store has never
        seen mean the repo was built by a DIFFERENT project's store — a wrong-target
        incident. Warning-only; a deliberate re-target of an old repo is legitimate."""
        foreign = foreign_scratch_correlations(self._console.conn, path)
        if foreign:
            self._log(
                f"⚠ {path} carries devharness scratch branches from correlation(s) this store has "
                f"never seen: {', '.join(foreign)} — another project's build target? verify before W"
            )

    def _prepare_target(self, path: str) -> str | None:
        """Make `path` a usable build target (existing git repo with a commit), creating + initializing
        it if needed. Returns None on success, else a one-line failure reason."""
        p = Path(path)
        if not p.exists():
            try:
                p.mkdir(parents=True)
                self._log(f"created {path}")
            except OSError as exc:
                return f"can't create {path}: {exc}"
        if not p.is_dir():
            return f"{path} is not a directory"
        if subprocess.run(["git", "-C", path, "rev-parse", "--git-dir"],
                          capture_output=True, text=True).returncode != 0:
            r = subprocess.run(["git", "-C", path, "init", "-q"], capture_output=True, text=True)
            if r.returncode != 0:
                return f"git init failed: {r.stderr.strip()}"
            self._log(f"git init {path}")
            # Seed a .gitignore covering bytecode caches (rev 0.3.58) — a T-created repo without one
            # let the worker's in-worktree test runs surface __pycache__ as scope violations, and
            # scratch commits shipped .pyc files. Only on repos WE create; an existing repo keeps
            # its own conventions.
            gi = Path(path) / ".gitignore"
            if not gi.exists():
                from devharness.worktree.hygiene import SEEDED_GITIGNORE

                gi.write_text(SEEDED_GITIGNORE, encoding="utf-8")
                subprocess.run(["git", "-C", path, "add", ".gitignore"], capture_output=True, text=True)
                self._log(f"seeded .gitignore in {path}")
        if subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                          capture_output=True, text=True).returncode != 0:
            r = subprocess.run(
                ["git", "-C", path, "-c", "user.name=devharness-dev",
                 "-c", "user.email=dev@devharness.local", "commit", "--allow-empty", "-m", "init", "-q"],
                capture_output=True, text=True)
            if r.returncode != 0:
                return f"initial commit failed: {r.stderr.strip()}"
            self._log(f"initial commit in {path}")
        # Git for Windows enables core.fsmonitor in its SYSTEM config; the harness fires many git ops
        # per worktree, so its daemon never settles and piles up -> SDK `initialize` timeouts. Disable it
        # on the target (devharness already has it off repo-locally).
        subprocess.run(["git", "-C", path, "config", "core.fsmonitor", "false"],
                       capture_output=True, text=True)
        return None

    def action_certify(self) -> None:
        self._prompt("certify — task_id:", lambda v: self._launch(
            "certify", lambda conn, bus: ConsoleReview(conn, bus).certify(v)))

    def action_oss_run(self) -> None:
        self._prompt("OSS run — correlation_id:", lambda v: self._launch(
            "oss run", lambda conn, bus: ConsoleOss(conn, bus).run(v)))

    def action_assemble(self) -> None:
        # assemble is a fast git merge (not a minutes-long worker) — run it on the UI thread via _act,
        # like the immediate decisions. Refusal mirrors W (an env target is valid without T).
        if self._target_path is None and not os.environ.get("DEVHARNESS_TARGET_REPO"):
            self._log("no build target set — press T to set the project repo first")
            return
        self._prompt_opt("assemble — correlation_id (blank = latest):", self._assemble)

    def _assemble(self, value: str) -> None:
        cid = value or self._latest_correlation()
        if not cid:
            self._log("no correlation — run research first (R)")
            return
        self._act(lambda: self._console.assemble(base_path=self._target_path).assemble(cid),
                  lambda summary: summary)

    def action_answer(self) -> None:
        self._prompt_opt(self._answer_prompt_text(), self._answer)

    def _answer_prompt_text(self) -> str:
        """The A prompt's label — the COMPLETE pending question, readable (rev 0.4.12: the 400-char
        summary showed only the FIRST divergence question of a multi-question round, so the operator
        answered questions they never saw). Direct DB read, restart-proof. May clip in the modal on
        a short terminal — accepted; no truncation is reintroduced."""
        pending_qid = self._latest_unanswered_question()
        if pending_qid:
            text = self._pending_question_text(pending_qid)
            if text:
                return f"question: {full_question_text(text)}\n\nyour answer:"
        return "your answer (to the latest question):"

    def _answer(self, value: str) -> None:
        question_id = self._latest_unanswered_question()
        if not question_id:
            self._log("no unanswered question")
            return
        if not value.strip():
            self._log("ERROR: type an answer")
            return
        self._act(lambda: self._console.research().submit_answer(question_id, value.strip()),
                  lambda r: f"answered {question_id}")

    def action_research(self) -> None:
        self._prompt("research — your project idea / seed:", self._start_research)

    def _start_research(self, seed: str) -> None:
        if self._begin("research"):
            self._active_worker = self._run_research(seed)

    @work(thread=True, exit_on_error=False, group="build")
    def _run_research(self, seed: str) -> None:
        from devharness.roles.research import ResearchRole
        worker = get_current_worker()
        conn = None
        try:
            conn = sqlite3.connect(self._console.db_path)
            conn.execute("PRAGMA busy_timeout=5000")
            correlation_id = f"tui-research-{int(time.time())}"

            def answer_fn(question_id, _question_text):
                # cancel-aware poll on the worker's own connection (WAL sees the operator's
                # submit_answer, written on the main connection).
                while not worker.is_cancelled:
                    for (payload,) in conn.execute(
                            "SELECT payload FROM events WHERE event_type='question_answered'"):
                        record = json.loads(payload)
                        if record.get("question_id") == question_id:
                            return record.get("answer_text", "")
                    time.sleep(0.5)
                raise _StepCancelled()

            self._ui(self._progress,
                     f"  research correlation_id = {correlation_id} (answer with A; "
                     "plan/dispatch with this id)")
            # research is advisory (T1) — route its interview/synthesis parallax to the cheaper model
            # (rev 0.3.82); the writer + verifier/reviewer keep frontier.
            role = ResearchRole.spawn(conn=conn, correlation_id=correlation_id,
                                      parallax=live_parallax_client(model=model_for_tier("T1")),
                                      event_bus=_ProxyBus(self), answer_fn=answer_fn)
            spec_id = asyncio.run(role.run(seed, correlation_id))
            if not worker.is_cancelled:
                self._ui(self._progress, f"✔ research: drafted spec {spec_id}")
        except _StepCancelled:
            pass
        except Exception as exc:  # noqa: BLE001
            if not worker.is_cancelled:
                self._ui(self._progress, f"✖ research: {type(exc).__name__}: {exc}")
        finally:
            if conn is not None:
                conn.close()
            self._ui(self._end)


def run() -> int:
    """Launch the interactive TUI (blocks until the operator quits)."""
    # The build steps drive the Claude Agent SDK + parallax via the claude.ai login, not an
    # API key — matching the run_* drivers' `env -u ANTHROPIC_API_KEY`. A stray ANTHROPIC_API_KEY
    # in the shell makes the SDK use it and the `claude` subprocess exit 1 ("Command failed with
    # exit code 1"), so clear it for this process before any build step spawns the SDK.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        tui = ConsoleTUI()
    except FileNotFoundError as exc:
        # A bad DEVHARNESS_DB (missing parent directory) fails closed in ConsoleApp.connect
        # with the resolved absolute path named — one clear line, not a traceback (rev 0.3.63).
        import sys
        sys.stderr.write(f"{exc}\n")
        return 1
    tui.run()
    return 0
