"""Operator console package.

A user-facing interface for driving the devharness loop directly, with a human
operator in the seat instead of an LLM agent: start research, sign the spec,
dispatch the director and developer, run the OSS path, and make the loop
decisions the agent currently makes.

It connects to the existing event-sourced runtime and reflects loop state
read-only by reading the projections the runtime maintains (Invariant 8 keeps
them in step with the event log). The sole write path is ``EventBus.emit_sync``
(the ``cli/_bus`` ``projected_bus`` writer) — the console never writes the event
store or a projection directly. ``ConsoleResearch`` is the first operator action
surface: start a research session and submit operator interview answers, issuing
the same operations as the ``run_research`` driver with each event attributed to
the operator. ``ConsoleSignoff`` is the sign-off gate surface: review the
synthesized spec and sign or reject it, with ``sign`` on the canonical sign path
(so the human sign-off gate, Invariant 4, is preserved) and ``reject`` recording
an operator-attributed refusal. ``ConsoleDirector`` is the director-dispatch
surface: dispatch the real ``DirectorRole`` to plan/decompose the signed spec,
issuing the same operations as the ``run_director`` driver and respecting the
director's write-free tool boundary. ``ConsoleDeveloper`` is the
developer-dispatch surface: dispatch the real ``DeveloperRole`` to write one plan
task, issuing the same operations as the ``run_developer`` driver — the developer
alone takes the single write lock and writes inside its isolated worktree
(Invariant 1), scope-bounded on its realized diff, completed only when
verifier-first acceptance and a fresh-context reviewer cert both pass (Invariant 5).
``ConsoleOss`` is the §S5 OSS-contribution surface: ``run`` drives the OSS path
end-to-end — intake hardening (cooldown + SPDX license + maintainer verification +
injection scan, fail-closed), then on accept dispatch the ``is_oss`` tasks through
the in-lock harness (four §S5 admission gates → fork-branch worktree → in-lock
verifier → bot-identity commit after the verifier passes → fresh-context reviewer
cert), then optionally open the pull request — issuing the same operations as the
``run_oss`` driver and preserving the §S5 identity split (bot commit, operator PR).
``ConsoleReview`` is the back-half surface: ``certify`` advances the fresh-context
read-only ``ReviewerRole`` (Invariant 2) and completes/rejects the task —
``completed`` still earned twice (Invariant 5) — and ``integrate`` advances the
director's integration decision; both record through ``EventBus.emit_sync``.
``ConsoleTaskDecision`` is the §S7 operator-review surface: ``accept`` / ``reject``
a retro CANDIDATE (an antibody or a gate-change) through the canonical
``retro.approval`` accept/reject operation, recording the loop decision as the
operator-attributed ``candidate_reviewed`` event (the human in the seat, not an
LLM) and preserving SC-2 (no auto-apply), Inv 11, and Inv 12 exactly.
``ConsoleRetro`` is that SAME §S7 operator-review decision in the
``devharness retro`` CLI's vocabulary: ``approve`` / ``reject`` a retro CANDIDATE,
issuing the same operations as ``devharness retro approve/reject`` and recording
the operator-attributed ``candidate_reviewed`` event — a thin CLI-faithful surface
over the shared ``ConsoleTaskDecision`` review logic, so SC-2, Inv 11, and Inv 12
hold unchanged. ``ConsoleEnactGateChange`` is the §S7 gate-change enactment
surface: ``list_approved`` surfaces the approved gate-change candidates an operator
could enact (SELECT-only) and ``enact`` issues the same operation as the canonical
gate-change enactment path (``retro.enacted_gate_changes.enact_gate_change``),
recording the operator-attributed ``gate_change_enacted`` event — refusing a
not-approved candidate, and (the canonical operation unchanged) Invariant 12 still
refuses any core-gate weakening. ``ConsolePrune`` is the §S6 operator-authorized
prune surface: ``list_expired`` surfaces the expired trust grants an authorized
prune would remove (SELECT-only) and ``prune`` issues the same operation as
``devharness prune`` (the canonical ``maintenance.prune.prune_expired_trust_grants``),
recording one operator-attributed ``trust_grant_pruned`` event per expired grant —
the §S6 delete path the advisory maintenance PruneCycle deliberately lacks, touching
only expired grants under the operator's required-reason authorization.

The live SSE consumer (``sse``) keeps the surfaced state in sync by consuming the
SAME sidecar feed the dashboard consumes — no parallel telemetry layer.
"""

from devharness.console.app import ConsoleApp
from devharness.console.developer import (
    AllTasksSettled,
    ConsoleDeveloper,
    NoPlan,
    UnknownTask,
    live_parallax_client,
)
from devharness.console.director import ConsoleDirector, NoSignedSpec, live_reasoning_client
from devharness.console.enact_gate_change import ConsoleEnactGateChange, GateChangeNotApproved
from devharness.console.oss import ConsoleOss, NoOssTasks
from devharness.console.prune import ConsolePrune, EmptyPruneReason
from devharness.console.research import ConsoleResearch, UnknownQuestion
from devharness.console.retro import ConsoleRetro
from devharness.console.review import (
    AlreadyTerminal,
    ConsoleReview,
    NoTerminalOutcome,
    NotReadyForReview,
    TaskNotStarted,
    UnknownPlan,
)
from devharness.console.signoff import ConsoleSignoff, EmptyRejectionReason, SPEC_REJECTED_EVENT
from devharness.console.sse import SSEFrame, StreamConsumer, parse_sse_frames, stream_url
from devharness.console.state import LoopState, read_loop_state
from devharness.console.task_decision import (
    CandidateNotFound,
    ConsoleTaskDecision,
    UnknownQueue,
)

__all__ = [
    "ConsoleApp",
    "ConsoleResearch",
    "UnknownQuestion",
    "ConsoleSignoff",
    "EmptyRejectionReason",
    "SPEC_REJECTED_EVENT",
    "ConsoleDirector",
    "NoSignedSpec",
    "live_reasoning_client",
    "ConsoleDeveloper",
    "NoPlan",
    "UnknownTask",
    "AllTasksSettled",
    "live_parallax_client",
    "ConsoleOss",
    "NoOssTasks",
    "ConsoleReview",
    "TaskNotStarted",
    "NotReadyForReview",
    "AlreadyTerminal",
    "NoTerminalOutcome",
    "UnknownPlan",
    "ConsoleTaskDecision",
    "ConsoleRetro",
    "UnknownQueue",
    "CandidateNotFound",
    "ConsoleEnactGateChange",
    "GateChangeNotApproved",
    "ConsolePrune",
    "EmptyPruneReason",
    "LoopState",
    "read_loop_state",
    "SSEFrame",
    "StreamConsumer",
    "parse_sse_frames",
    "stream_url",
]
