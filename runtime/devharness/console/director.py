"""Operator console director action — dispatch the director to plan/decompose the signed spec.

The operator drives the loop directly, with no LLM agent in the operator seat making the
*dispatch* decision: ``plan`` resolves the signed spec for a correlation and dispatches the
real ``DirectorRole`` to plan it — issuing the SAME operations as the ``run_director`` driver
(resolve the latest operator-signed spec → spawn ``DirectorRole`` → ``run`` it plan-only,
decomposing the spec via mcp-reasoning when no task list is injected, or planning an injected
list). The director itself remains the planning agent (mcp-reasoning + parallax); the console
action is the operator pressing "dispatch". Like ``run_director`` it runs plan-only — no
``developer_role_cls``, so the director never dispatches a developer here.

The director's tool boundary is respected exactly: ``DirectorRole`` carries no write tools
(``allowed_mcp_servers`` is ``["mcp-reasoning", "parallax"]`` and ``tool_inventory`` is
mutation-free), so dispatching it can never write a file. The plan it drafts is persisted as a
``plan`` artifact and announced via ``plan_drafted`` through ``EventBus.emit_sync`` — the
console's sole sanctioned write path; the director never writes the event store or a projection
directly. Spec resolution is SELECT-only.
"""

import asyncio
import json
import time
from pathlib import Path

from devharness.mcp.base import TRANSIENT_SDK_RESULT
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.roles.director import DirectorRole

_SDK_RETRIES = 2  # attempts to retry the transient 'error result: success' SDK glitch (rev 0.3.86)


class NoSignedSpec(RuntimeError):
    """Raised when the operator dispatches the director with no signed spec to plan."""


def _reasoning_server_config(name: str = "mcp-reasoning") -> dict:
    """Read a named MCP server's live launch spec from ~/.claude.json (never embed it).

    Mirrors ``run_director``'s ``_server_config``: the launch spec is operator-local and
    machine-specific, so it is read live, never committed.
    """
    path = Path.home() / ".claude.json"
    if not path.exists():
        raise RuntimeError(f"no {path} — cannot find the {name} MCP server launch spec")
    server = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {}).get(name)
    if not server:
        raise RuntimeError(f"{name} not found under mcpServers in ~/.claude.json")
    return {name: server}


def live_reasoning_client() -> MCPReasoningClient:
    """The live mcp-reasoning client, built from ~/.claude.json (as ``run_director`` builds it)."""
    return MCPReasoningClient(mcp_servers=_reasoning_server_config())


class ConsoleDirector:
    """Operator-driven director dispatch: plan/decompose the signed spec via the real DirectorRole.

    Constructed against the console connection and its ``EventBus`` writer (the emit-only write
    path). ``plan`` resolves the signed spec, spawns ``DirectorRole``, and runs it plan-only —
    the same operations as the ``run_director`` driver. The director's plan_drafted /
    director_decision events flow through the supplied ``EventBus`` (Invariant 8 projections
    stay in step); the planning agent's tool boundary is unchanged (no write tools).
    """

    def __init__(self, conn, writer, *, now_millis=None):
        self._conn = conn
        self._writer = writer  # an EventBus — emit_sync is the only sanctioned write path
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))

    def spawn_director(self, correlation_id, *, reasoning) -> DirectorRole:
        """Spawn the DirectorRole the dispatch runs — read/plan only, no write tools.

        Exposed so the tool boundary can be inspected (``allowed_mcp_servers`` /
        ``tool_inventory`` carry no mutation tools). ``run_director`` spawns the role the same way.
        """
        return DirectorRole.spawn(
            conn=self._conn,
            correlation_id=correlation_id,
            reasoning=reasoning,
            event_bus=self._writer,
            now_millis=self._now_millis,
        )

    def plan(self, correlation_id, *, spec_id=None, tasks=None, reasoning=None):
        """Dispatch the director to plan the signed spec; return the plan_id (None if it refuses).

        Resolves the most recent operator-signed spec for ``correlation_id`` (an explicit
        ``spec_id`` overrides resolution), then spawns + runs ``DirectorRole`` plan-only. When
        ``tasks`` is None the director decomposes the spec via mcp-reasoning (#2b), else it plans
        the injected list — exactly the ``run_director`` choice. ``reasoning`` defaults to the
        live mcp-reasoning client. Returns the drafted plan_id, or None when the director refuses
        (an unsigned spec). Raises ``NoSignedSpec`` when no signed spec exists to plan.
        """
        spec_id = spec_id or self._latest_signed_spec(correlation_id)
        if spec_id is None:
            raise NoSignedSpec(
                f"no signed spec for correlation_id {correlation_id!r} — "
                "run + sign research first"
            )
        reasoning = reasoning or live_reasoning_client()
        # Retry the transient SDK 'error result: success' glitch (it failed the director twice before
        # succeeding on the first real VPS drive, rev 0.3.86) — a fresh director per attempt; the latest
        # plan_drafted wins, so a partial earlier attempt's director_decision noise is harmless. Any
        # other error propagates immediately.
        for attempt in range(_SDK_RETRIES + 1):
            director = self.spawn_director(correlation_id, reasoning=reasoning)
            try:
                return asyncio.run(director.run(spec_id, correlation_id, tasks=tasks))
            except Exception as exc:  # noqa: BLE001
                if attempt < _SDK_RETRIES and TRANSIENT_SDK_RESULT in str(exc):
                    continue
                raise

    # --- read-only lookups (SELECT-only; no event-store or projection writes) ---

    def _latest_signed_spec(self, correlation_id):
        row = self._conn.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE artifact_type = 'spec' AND correlation_id = ? AND signed = 1 "
            "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1",
            (correlation_id,),
        ).fetchone()
        return row[0] if row else None
