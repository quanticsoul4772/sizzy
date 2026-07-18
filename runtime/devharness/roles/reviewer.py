"""Reviewer role — independent certification (B2.5, §Architecture R4, Invariant 2).

A single parallax-backed reviewer (OQ5, spec rev 0.3.8): one Agent SDK worker per
certification, run in a fresh context (zero inherited history, setting_sources=[]),
with a read-only tool inventory. Runs the B2.2 falsifiers (parallax verify/check/
grounded_verify + test_suite) and aggregates to a single verdict. Zero write tools,
asserted at construction (Inv 2).
"""

import time
from uuid import uuid4

import msgspec

from devharness.call_class import classify
from devharness.events.registry import ReviewerCertified, ReviewerRejected
from devharness.mcp.parallax import PARALLAX_TOOLS
from devharness.roles.base import AgentRole
from devharness.roles.fresh_context import require_fresh_context
from devharness.verifier.base import VerifierOk
from devharness.verifier.registry import FALSIFIERS

# The reviewer's ACI tools: read + run the suite only. No write_file/append/run_command.
REVIEWER_ACI_TOOLS = ["open_file", "read_range", "run_tests"]

# The reviewer re-runs the task's acceptance criterion in a fresh context (done earned twice,
# Inv 5). The default is test_suite — the universally-applicable independent re-verification.
# rev 0.3.22 (finding #2c): the prior claim-based default misfired on tasks that supply neither
# a computable claim nor verbatim sources (a new_project_scaffold cert would fail
# parallax_grounded_verify on empty sources and certify nothing real via parallax_check). Callers
# whose task carries a genuine claim + sources (e.g. feature tasks) pass CLAIM_VERIFIERS instead.
REVIEW_VERIFIERS = ["test_suite"]
CLAIM_VERIFIERS = ["parallax_verify", "parallax_check", "parallax_grounded_verify", "test_suite"]

_WRITE_TOOL_NAMES = ("Edit", "Write", "Bash", "NotebookEdit", "write_file", "append_to_file", "run_command")


def reviewer_tool_inventory() -> list[str]:
    """The reviewer's read-only inventory: parallax non-mutation tools + ACI read/test."""
    tools = []
    for tool in PARALLAX_TOOLS:
        full = f"mcp__parallax__{tool}"
        if classify(full) != "mutation":  # drops save/forget
            tools.append(full)
    for tool in REVIEWER_ACI_TOOLS:
        tools.append(f"mcp__devharness-aci__{tool}")
    return tools


class ReviewerWriteToolError(RuntimeError):
    """Raised when a reviewer is constructed with any write-capable tool in its inventory."""


class ReviewerRole(AgentRole):
    ALLOWED_MCP_SERVERS = ["parallax", "devharness-aci"]

    def __init__(self, *, parallax, event_bus, conn, context, fresh_context,
                 verifiers=None, now_millis=None):
        require_fresh_context(fresh_context, "ReviewerRole")
        self.fresh_context = True
        self.parallax = parallax
        self.event_bus = event_bus
        self.conn = conn
        self.context = context  # harness-assembled
        self.verifiers = list(verifiers) if verifiers is not None else list(REVIEW_VERIFIERS)
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))
        self._assert_no_write_tools()

    def _assert_no_write_tools(self) -> None:
        inv = self.tool_inventory
        for tool in inv:
            if classify(tool) == "mutation":
                raise ReviewerWriteToolError(f"reviewer inventory has a mutation tool: {tool}")
            if any(name in tool for name in _WRITE_TOOL_NAMES):
                raise ReviewerWriteToolError(f"reviewer inventory has a write tool: {tool}")

    @property
    def allowed_mcp_servers(self) -> list[str]:
        return list(self.ALLOWED_MCP_SERVERS)

    @property
    def tool_inventory(self) -> list[str]:
        return reviewer_tool_inventory()

    @classmethod
    def assemble_context(cls, conn, correlation_id) -> dict:
        # a fresh reviewer assembles only the harness facts it needs — not the writer's session
        events = conn.execute(
            "SELECT event_type FROM events WHERE correlation_id = ? ORDER BY seq", (correlation_id,)
        ).fetchall()
        return {"correlation_id": correlation_id, "prior_events": [row[0] for row in events]}

    @classmethod
    def spawn(cls, *, conn, correlation_id, parallax, event_bus, fresh_context=False, **kwargs):
        return cls(
            parallax=parallax, event_bus=event_bus, conn=conn,
            context=cls.assemble_context(conn, correlation_id), fresh_context=fresh_context, **kwargs,
        )

    async def run(self, task_id, spec_artifact_id, plan_artifact_id, correlation_id):
        session_id = uuid4().hex  # a fresh reviewer session per certification
        # Independent re-verification judges the feature's actual claim against the realized diff —
        # the same OBJECTIVE artifacts the developer's acceptance used (the fresh context bars the
        # developer's session/reasoning, not the diff). A bare "task X completes spec Y per plan Z"
        # identifier string carries no evidence, so parallax.verify correctly refuses it and the
        # reviewer rejected every real feature whose acceptance had already passed.
        spec_claim = self.context.get("spec_claim") or self.context.get("claim")
        identifier_claim = f"task {task_id} completes spec {spec_artifact_id} per plan {plan_artifact_id}"
        # Forward the FULL verifier context the developer's acceptance used — the diff, the test
        # command, cwd, checkpoint, and every class-specific field (regression_command for bugfix,
        # pass_fail_command for refactor, the dependency-bump descriptors) — so the reviewer can
        # independently re-run the SAME per-class verifier for ANY class, not only feature/test_suite.
        # Override only the parallax client (a fresh session) and the claim grounding. Hand-picking a
        # few fields here was the bug that left the reviewer unable to certify bugfix/refactor/
        # dependency_bump (it read keys the verifier never received).
        verifier_context = dict(self.context)
        verifier_context.pop("prior_events", None)
        verifier_context.update({
            "parallax": self.parallax,
            "spec_claim": spec_claim or identifier_claim,
            "claim": spec_claim or identifier_claim,
            "task_id": task_id,
            "correlation_id": correlation_id,
        })
        evidence = {}
        failures = []
        for name in self.verifiers:
            result = await FALSIFIERS[name].verify(verifier_context)
            evidence[name] = getattr(result, "evidence", {})
            if not isinstance(result, VerifierOk):
                failures.append((name, result.reason))

        if failures:
            reason = "; ".join(f"{name}: {detail}" for name, detail in failures)
            self.event_bus.emit_sync(
                "reviewer_rejected",
                msgspec.to_builtins(ReviewerRejected(
                    task_id=task_id, reviewer_session_id=session_id, reason=reason,
                    evidence=evidence, correlation_id=correlation_id, rejected_at_millis=self._now_millis(),
                )),
                correlation_id=correlation_id,
            )
            return False
        self.event_bus.emit_sync(
            "reviewer_certified",
            msgspec.to_builtins(ReviewerCertified(
                task_id=task_id, reviewer_session_id=session_id, evidence=evidence,
                correlation_id=correlation_id, certified_at_millis=self._now_millis(),
            )),
            correlation_id=correlation_id,
        )
        return True
