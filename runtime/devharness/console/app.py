"""Operator console application skeleton (read-only display + emit-only writer).

``ConsoleApp.connect()`` opens the existing runtime's SQLite event store, brings
it to the current schema (``migrate``), and prepares the sole write path — a
``projected_bus`` ``EventBus``, so any state-changing operator action goes
through ``EventBus.emit_sync`` (never a direct event-store or projection write).
The skeleton itself only reads: ``loop_state()`` derives display state from the
projections, and ``render()`` formats it for display.

``research()`` exposes the first operator action surface — start a research
session and submit operator interview answers (``ConsoleResearch``), issuing the
same operations as the ``run_research`` driver but with a human in the seat and
each event attributed to the operator.

``signoff()`` exposes the operator sign-off gate — review the synthesized spec
and sign or reject it (``ConsoleSignoff``). ``sign`` routes through the canonical
sign path so the human sign-off gate (Invariant 4) is preserved exactly; ``reject``
records an operator-attributed refusal and leaves the spec unsigned.

``director()`` exposes the director-dispatch surface — dispatch the real
``DirectorRole`` to plan/decompose the signed spec (``ConsoleDirector``), issuing
the same operations as the ``run_director`` driver and respecting the director's
write-free tool boundary. The director remains the planning agent; the console
action is the operator pressing "dispatch", plan-only (it never dispatches a
developer).

``developer()`` exposes the developer-dispatch surface — dispatch the real
``DeveloperRole`` to write one plan task (``ConsoleDeveloper``), issuing the same
operations as the ``run_developer`` driver. The developer alone takes the single
write lock and writes inside its isolated worktree (Invariant 1), scope-bounded on
its realized diff; verifier-first acceptance + a fresh-context reviewer
certification complete the task only when both pass (Invariant 5). The console adds
no write path of its own; the action is the operator pressing "dispatch developer".

``oss()`` exposes the §S5 OSS-contribution surface — drive the OSS path end-to-end
(``ConsoleOss``), issuing the same operations as the ``run_oss`` driver: intake
hardening (cooldown + SPDX license + maintainer verification + injection scan,
fail-closed), then on accept dispatch the ``is_oss`` tasks through the in-lock
harness (four §S5 admission gates → fork-branch worktree → in-lock verifier →
bot-identity commit after the verifier passes → fresh-context reviewer cert), then
optionally open the pull request. The §S5 identity split is preserved exactly: the
contribution commit is authored by the bot identity, the pull request by the
operator. The console adds no write path of its own; Invariant 1 holds (the
``DeveloperRole`` alone takes the single write lock and writes inside its isolated
fork-branch worktree), and the action is the operator pressing "run OSS".

``review()`` exposes the back half of the loop as discrete operator decisions
(``ConsoleReview``): ``certify`` advances the fresh-context read-only
``ReviewerRole`` (Invariant 2) and completes/rejects the task — ``completed`` is
still earned twice (verifier pass AND reviewer cert, Invariant 5); ``integrate``
advances the director's integration decision. Both record through ``emit_sync``.

``task_decision()`` exposes the §S7 operator-review surface (``ConsoleTaskDecision``):
``accept`` / ``reject`` a retro CANDIDATE (an antibody or a gate-change) through the
canonical ``retro.approval`` accept/reject operation. The decision is recorded as the
operator-attributed ``candidate_reviewed`` event (the human in the seat, not an LLM) —
the sole path from a CANDIDATE to an enacted change (SC-2, no auto-apply), preserving
text-only enforcement (Inv 11) and the core-gate-unweakable guard (Inv 12) exactly.

``retro()`` exposes the SAME §S7 operator-review decision in the ``devharness retro``
CLI's vocabulary (``ConsoleRetro``): ``approve`` / ``reject`` a retro CANDIDATE,
issuing the same operations as ``devharness retro approve/reject`` and recording the
operator-attributed ``candidate_reviewed`` event. It is a thin CLI-faithful surface
over the shared ``ConsoleTaskDecision`` review logic, so SC-2, Inv 11, and Inv 12 hold
unchanged.

``enact_gate_change()`` exposes the §S7 gate-change enactment surface
(``ConsoleEnactGateChange``): ``list_approved`` surfaces the approved gate-change
candidates an operator could enact (SELECT-only); ``enact`` issues the same operation
as the canonical gate-change enactment path
(``retro.enacted_gate_changes.enact_gate_change``), recording the operator-attributed
``gate_change_enacted`` event. It refuses a not-approved candidate and — because the
canonical operation is used unchanged — Invariant 12 still refuses any core-gate
weakening (and a non-auto-applicable change is refused before any event is emitted).
The console adds no path around the enactment operation, only the operator seat in
front of it.

``prune()`` exposes the §S6 operator-authorized prune surface (``ConsolePrune``):
``list_expired`` surfaces the expired trust grants an authorized prune would remove
(SELECT-only); ``prune`` issues the same operation as ``devharness prune`` (the
canonical ``maintenance.prune.prune_expired_trust_grants``), recording one
operator-attributed ``trust_grant_pruned`` event per expired grant. It is the §S6
delete path the advisory maintenance PruneCycle deliberately lacks — only expired,
non-revoked grants are touched, and the operator authorization (a required reason) is
the ``pruned_by`` attribution. The console adds no path around the prune operation,
only the operator seat in front of it.

``follow()`` keeps the surfaced state live by consuming the sidecar's SSE feed —
the SAME event surface the dashboard consumes, not a parallel telemetry layer.
Each frame the sidecar broadcasts (the single event log it tails) prompts the
console to re-derive its display from the projections; Invariant 8 keeps those
projections in step with the event log, so the SSE feed and the displayed state
never drift.
"""

import os
import sqlite3
from pathlib import Path
from typing import Callable

from devharness.cli._bus import projected_bus
from devharness.console.assemble import ConsoleAssemble
from devharness.console.developer import ConsoleDeveloper
from devharness.console.director import ConsoleDirector
from devharness.console.enact_gate_change import ConsoleEnactGateChange
from devharness.console.oss import ConsoleOss
from devharness.console.prune import ConsolePrune
from devharness.console.research import ConsoleResearch
from devharness.console.retro import ConsoleRetro
from devharness.console.review import ConsoleReview
from devharness.console.signoff import ConsoleSignoff
from devharness.console.sse import SSEFrame, StreamConsumer
from devharness.console.state import LoopState, read_loop_state
from devharness.console.task_decision import ConsoleTaskDecision
from devharness.events.bus import EventBus
from devharness.migrate import migrate

DEFAULT_DB = "var/devharness.db"


class ConsoleApp:
    """The operator console skeleton: connect, read loop state, render, follow, act."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.environ.get("DEVHARNESS_DB", DEFAULT_DB)
        self._conn: sqlite3.Connection | None = None
        self._writer: EventBus | None = None
        self._synced_state: LoopState | None = None
        self._last_frame: SSEFrame | None = None
        self._live_seq: int = 0
        self._store_created = False

    def connect(self) -> "ConsoleApp":
        """Open the event store, migrate it, and arm the emit-only write path.

        Store-path hygiene (rev 0.3.63): a file path is resolved to ABSOLUTE before opening
        — sqlite errors name no path, and a relative ``DEVHARNESS_DB`` against the wrong cwd
        either fails bare ("unable to open database file") or, worse, silently CREATES a
        fresh empty store at the wrong location that ``migrate`` then makes look legitimate
        (the store-side analog of the rev-0.3.61 wrong-target contamination). A missing
        parent directory fails closed with the resolved path named; a missing FILE under an
        existing parent is still created — the documented one-keypress new-project flow —
        but ``store_created`` records it so the operator surfaces announce the new store.
        """
        if self._db_path != ":memory:":
            resolved = Path(self._db_path).resolve()
            if not resolved.parent.is_dir():
                raise FileNotFoundError(
                    f"event-store directory does not exist: {resolved.parent} "
                    f"(DEVHARNESS_DB resolved to {resolved}) — run from the repo root "
                    "or set DEVHARNESS_DB to an absolute path"
                )
            # rev 0.4.13 content gate (parity with the panel's _resolve_db): migrate() below
            # would write devharness schema into an existing foreign sqlite file.
            if resolved.exists():
                from devharness.migrate import is_event_store

                verdict = is_event_store(resolved)
                if verdict is False:
                    raise FileNotFoundError(
                        f"{resolved} exists but is not a devharness event store — refusing to "
                        "migrate a foreign database (delete or rename the file if it should be "
                        "a new store)")
                if verdict is None:
                    raise FileNotFoundError(
                        f"{resolved} exists but is unreadable right now — refusing to open a "
                        "store that cannot even be probed (locked by another process?)")
            self._store_created = not resolved.exists()
            self._db_path = str(resolved)
        self._conn = sqlite3.connect(self._db_path)
        # WAL + a busy timeout so a build-step worker can open its OWN connection to the
        # same file (for its reads) and see the main connection's committed writes while a
        # build runs. WAL is a no-op on :memory: (which can't drive build steps anyway).
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        migrate(self._conn)
        # The sole write path for any operator action: EventBus.emit_sync.
        self._writer = projected_bus(self._conn)
        return self

    @property
    def db_path(self) -> str:
        """The event-store path — a build-step worker opens its own connection to it.
        Absolute after ``connect()`` for a file-backed store (worker threads and mid-session
        cwd changes must never re-resolve it differently)."""
        return self._db_path

    @property
    def store_created(self) -> bool:
        """True when ``connect()`` created a brand-new store file (vs opening an existing
        one) — the operator surfaces announce this loudly, because a fresh empty store at
        an unintended path is contamination-shaped (rev 0.3.63)."""
        return self._store_created

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("ConsoleApp is not connected; call connect() first")
        return self._conn

    @property
    def writer(self) -> EventBus:
        """The EventBus — emit_sync is the only sanctioned write path."""
        if self._writer is None:
            raise RuntimeError("ConsoleApp is not connected; call connect() first")
        return self._writer

    def research(self, *, operator: str | None = None) -> ConsoleResearch:
        """Operator research actions: start a session, ask/answer interview questions.

        Bound to the console connection and its emit-only ``EventBus`` writer, so every
        action it issues is recorded through ``EventBus.emit_sync`` and attributed to the
        operator (``operator`` defaults to the harness operator identity).
        """
        return ConsoleResearch(self.conn, self.writer, operator=operator)

    def signoff(self, *, operator: str | None = None) -> ConsoleSignoff:
        """Operator sign-off actions: review the synthesized spec and sign or reject it.

        Bound to the console connection and its emit-only ``EventBus`` writer. ``sign``
        routes through the canonical sign path so the human sign-off gate (Invariant 4 /
        commitment 12) is preserved; ``reject`` records an operator-attributed refusal and
        leaves the spec unsigned. ``operator`` defaults to the harness operator identity.
        """
        return ConsoleSignoff(self.conn, self.writer, operator=operator)

    def director(self) -> ConsoleDirector:
        """Operator director dispatch: plan/decompose the signed spec via the real DirectorRole.

        Bound to the console connection and its emit-only ``EventBus`` writer. ``plan`` issues
        the same operations as the ``run_director`` driver (resolve the signed spec → spawn
        ``DirectorRole`` → run it plan-only, decomposing the spec via mcp-reasoning unless a task
        list is injected). The director is the planning agent and keeps its write-free tool
        boundary; this action is the operator dispatching it.
        """
        return ConsoleDirector(self.conn, self.writer)

    def developer(self, **kwargs) -> ConsoleDeveloper:
        """Operator developer dispatch: write one plan task via the real DeveloperRole.

        Bound to the console connection and its emit-only ``EventBus`` writer. ``dispatch``
        issues the same operations as the ``run_developer`` driver (resolve the signed spec +
        plan → select the task → dispatch via ``DirectorRole.dispatch`` -> ``DeveloperRole`` →
        verifier-first acceptance + fresh-context reviewer cert → integrate). The developer
        alone holds the single write lock and writes inside its isolated worktree (Invariant 1),
        scope-bounded on its realized diff; the console adds no write path of its own. ``kwargs``
        (``base_path`` / ``test_target`` / ``test_command``) configure the write target.
        """
        return ConsoleDeveloper(self.conn, self.writer, **kwargs)

    def assemble(self, **kwargs) -> ConsoleAssemble:
        """Operator assemble action: merge a built project's final task branch into the target's main —
        the loop's terminal adopt step (previously a manual git merge). ``base_path`` selects the target;
        the assembly is recorded through ``EventBus.emit_sync``."""
        return ConsoleAssemble(self.conn, self.writer, **kwargs)

    def oss(self, **kwargs) -> ConsoleOss:
        """Operator OSS contribution: drive the §S5 OSS path via the real Director/Developer/Reviewer.

        Bound to the console connection and its emit-only ``EventBus`` writer. ``run`` issues the
        same operations as the ``run_oss`` driver: intake hardening (cooldown + SPDX license +
        maintainer verification + injection scan, fail-closed), then on accept dispatch the
        ``is_oss`` tasks through the in-lock harness (four §S5 admission gates → fork-branch
        worktree → in-lock verifier → bot-identity commit after the verifier passes →
        fresh-context reviewer cert), then optionally open the pull request. The §S5 identity
        split is preserved exactly — the contribution commit is the bot's, the pull request is the
        operator's. The console adds no write path of its own; Invariant 1 holds (the
        ``DeveloperRole`` alone takes the single write lock). ``kwargs`` (``base_path`` /
        ``test_target`` / ``test_command``) configure the upstream write target.
        """
        return ConsoleOss(self.conn, self.writer, **kwargs)

    def review(self) -> ConsoleReview:
        """Operator review/integrate actions: advance the reviewer cert + the integration decision.

        Bound to the console connection and its emit-only ``EventBus`` writer. ``certify`` runs
        the real fresh-context read-only ``ReviewerRole`` (zero write tools, Invariant 2) and
        completes/rejects the task — ``completed`` is earned twice (verifier pass AND reviewer
        cert, Invariant 5). ``integrate`` advances the director's integration decision through the
        canonical ``roles.integration.integrate``. Both record through ``EventBus.emit_sync``.
        """
        return ConsoleReview(self.conn, self.writer)

    def task_decision(self, *, operator: str | None = None) -> ConsoleTaskDecision:
        """Operator §S7 review actions: accept or reject a retro CANDIDATE.

        Bound to the console connection and its emit-only ``EventBus`` writer. ``accept`` /
        ``reject`` press the operator review decision through the canonical ``retro.approval``
        accept/reject operation, recording the loop decision as the operator-attributed
        ``candidate_reviewed`` event — the sole path from a CANDIDATE to an enacted change (SC-2,
        no auto-apply), preserving Inv 11 (text-only antibodies) and Inv 12 (core gates
        unweakable) exactly. ``operator`` defaults to the harness operator identity.
        """
        return ConsoleTaskDecision(self.conn, self.writer, operator=operator)

    def retro(self, *, operator: str | None = None) -> ConsoleRetro:
        """Operator §S7 review actions in the ``devharness retro`` CLI's vocabulary.

        Bound to the console connection and its emit-only ``EventBus`` writer. ``approve`` /
        ``reject`` press the operator review decision, issuing the same operations as
        ``devharness retro approve/reject`` (the canonical ``retro.approval`` operation) and
        recording the operator-attributed ``candidate_reviewed`` event — the sole path from a
        CANDIDATE to an enacted change (SC-2, no auto-apply), preserving Inv 11 (text-only
        antibodies) and Inv 12 (core gates unweakable) exactly. A thin CLI-faithful surface over
        the shared ``ConsoleTaskDecision`` review logic. ``operator`` defaults to the harness
        operator identity.
        """
        return ConsoleRetro(self.conn, self.writer, operator=operator)

    def enact_gate_change(self, *, operator: str | None = None) -> ConsoleEnactGateChange:
        """Operator §S7 gate-change enactment: enact an approved gate-change candidate.

        Bound to the console connection and its emit-only ``EventBus`` writer. ``list_approved``
        surfaces the approved gate-change candidates an operator could enact (SELECT-only);
        ``enact`` issues the same operation as the canonical gate-change enactment path
        (``retro.enacted_gate_changes.enact_gate_change``), recording the operator-attributed
        ``gate_change_enacted`` event (the operator is ``enacted_by``). It refuses a not-approved
        candidate; because the canonical operation is used unchanged, Invariant 12 still refuses
        any core-gate weakening (and a non-auto-applicable change is refused) before any event is
        emitted. ``operator`` defaults to the harness operator identity.
        """
        return ConsoleEnactGateChange(self.conn, self.writer, operator=operator)

    def prune(self, *, operator: str | None = None) -> ConsolePrune:
        """Operator §S6 prune actions: authorize the removal of expired trust grants.

        Bound to the console connection and its emit-only ``EventBus`` writer. ``list_expired``
        surfaces the expired, non-revoked trust grants an authorized prune would remove
        (SELECT-only); ``prune`` issues the same operation as ``devharness prune`` (the canonical
        ``maintenance.prune.prune_expired_trust_grants``), recording one operator-attributed
        ``trust_grant_pruned`` event per expired grant. It is the §S6 delete path the advisory
        maintenance PruneCycle deliberately lacks — only expired grants are touched, and the
        required reason is the operator authorization (the ``pruned_by`` attribution). ``operator``
        defaults to the harness operator identity.
        """
        return ConsolePrune(self.conn, self.writer, operator=operator)

    def loop_state(self) -> LoopState:
        """Read-only snapshot of the loop, derived from the projections."""
        return read_loop_state(self.conn)

    @property
    def last_frame(self) -> SSEFrame | None:
        """The most recent SSE frame seen while following the stream."""
        return self._last_frame

    @property
    def live_seq(self) -> int:
        """Highest event ``seq`` observed on the live stream (0 if none yet)."""
        return self._live_seq

    def synced_state(self) -> LoopState | None:
        """The loop state as of the last frame followed (None before any frame)."""
        return self._synced_state

    def follow(
        self,
        *,
        consumer: StreamConsumer | None = None,
        on_frame: Callable[[SSEFrame, LoopState], None] | None = None,
        max_frames: int | None = None,
    ) -> LoopState:
        """Consume the live SSE stream, keeping the surfaced loop state in sync.

        For each frame the sidecar broadcasts, re-derive the loop state from the
        projections — the console reflects the same event surface the dashboard
        consumes (the sidecar's ``/events/all`` channel), with no parallel
        telemetry channel. ``on_frame`` is invoked per frame with the frame and
        the freshly-derived state; ``max_frames`` bounds the consumption (a test
        seam — the live stream is otherwise unbounded). Returns the final state.
        """
        consumer = consumer or StreamConsumer()
        count = 0
        for frame in consumer.frames():
            self._last_frame = frame
            if frame.seq > self._live_seq:
                self._live_seq = frame.seq
            self._synced_state = self.loop_state()
            if on_frame is not None:
                on_frame(frame, self._synced_state)
            count += 1
            if max_frames is not None and count >= max_frames:
                break
        if self._synced_state is None:
            self._synced_state = self.loop_state()
        return self._synced_state

    def render(self) -> str:
        """Format the current loop state for display (read-only)."""
        state = self.loop_state()
        lines = ["=== devharness operator console ==="]
        lines.append(f"active role: {state.active_role or '(none)'}")
        if state.spec_signed:
            lines.append(f"spec: signed {state.signed_spec_id} by {state.signed_by or '(unknown)'}")
        else:
            lines.append("spec: (unsigned)")
        if state.tasks_by_state:
            tasks = ", ".join(f"{s}={n}" for s, n in sorted(state.tasks_by_state.items()))
            lines.append(f"tasks: {tasks}")
        else:
            lines.append("tasks: (none)")
        lines.append(f"events: {state.event_count}")
        return "\n".join(lines)
