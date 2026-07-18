"""Shared MCP client base over the Claude Agent SDK (B1.0).

Every MCP client invokes its server through the Claude Agent SDK with the
governing-layer posture ``setting_sources=[]`` (commitment 3): no CLAUDE.md or
settings inheritance into agent sessions. The SDK entry point (``query``) is
injectable so the substrate is testable without spawning a worker; the default
is the real ``claude_agent_sdk.query``. Per-call cost is read from the SDK's
``ResultMessage.total_cost_usd`` and accumulated.
"""

import json
from dataclasses import dataclass

import claude_agent_sdk as sdk

from devharness.models import default_model

# The Claude Agent SDK occasionally returns a ResultMessage flagged is_error while its subtype is
# "success" — a contradictory, transient glitch (query.py raises "Claude Code returned an error result:
# success"). It cleared on retry live (it failed the director twice, then succeeded). Callers match this
# substring to retry ONLY this transient, never a real failure (rev 0.3.86).
TRANSIENT_SDK_RESULT = "returned an error result: success"


@dataclass
class CallResult:
    """One MCP tool invocation's result plus the SDK-reported cost."""

    output: object
    cost_usd: float
    usage: object
    is_error: bool


def tool_prompt(server: str, tool: str, params: dict) -> str:
    """The instruction that drives the agent to call one MCP tool and return it."""
    return (
        f"Call the `{tool}` tool from the `{server}` MCP server with the "
        f"following arguments and return its result verbatim:\n"
        f"{json.dumps(params, sort_keys=True)}"
    )


class MCPClient:
    """Base for a per-server MCP client driven through the Agent SDK."""

    # Commitment 3 posture: agent sessions never inherit filesystem settings.
    SETTING_SOURCES: list = []

    def __init__(self, *, server_name, tools, mcp_servers, model=None, query_fn=None):
        self.server_name = server_name
        self.tools = list(tools)
        # MCP tool names are mcp__<server>__<tool>; only these are allowed.
        self.allowed_tools = [f"mcp__{server_name}__{tool}" for tool in self.tools]
        self.setting_sources = list(self.SETTING_SOURCES)  # always []
        self.mcp_servers = dict(mcp_servers)
        self.model = model or default_model()  # explicit kwarg > DEVHARNESS_MODEL > built-in default
        self._query_fn = query_fn or sdk.query
        self.last_cost_usd = None
        self.total_cost_usd = 0.0

    def options(self) -> "sdk.ClaudeAgentOptions":
        return sdk.ClaudeAgentOptions(
            setting_sources=self.setting_sources,
            mcp_servers=self.mcp_servers,
            allowed_tools=self.allowed_tools,
            model=self.model,
        )

    async def call(self, tool: str, params: dict) -> CallResult:
        """Invoke one tool on this server via the Agent SDK; return its result + cost."""
        if tool not in self.tools:
            raise ValueError(f"{tool!r} is not a tool of the {self.server_name} server")
        return await self._run(tool_prompt(self.server_name, tool, params))

    async def complete(self, prompt: str) -> CallResult:
        """A free-form completion (no named tool) through the Agent SDK, with this client's
        posture (setting_sources=[], MCP servers, model). For structured synthesis/decomposition
        where the role needs the model to compose JSON rather than invoke a server tool."""
        return await self._run(prompt)

    async def _run(self, prompt: str) -> CallResult:
        from devharness.sdk_query import run_query  # overage auth-fallback (rev 0.4.0)

        result = None
        async for message in run_query(self._query_fn, prompt, self.options()):
            if hasattr(message, "total_cost_usd"):
                result = message
        if result is None:
            raise RuntimeError("agent query produced no ResultMessage")
        cost = float(getattr(result, "total_cost_usd", 0.0) or 0.0)
        self.last_cost_usd = cost
        self.total_cost_usd += cost
        return CallResult(
            output=getattr(result, "result", None),
            cost_usd=cost,
            usage=getattr(result, "usage", None),
            is_error=bool(getattr(result, "is_error", False)),
        )
