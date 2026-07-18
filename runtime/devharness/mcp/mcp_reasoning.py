"""mcp-reasoning MCP client wrapper (B1.0).

Wraps the director's mcp-reasoning tools (`reasoning_decision` at forks,
`reasoning_reflection` for self-critique, `reasoning_meta`), each routed through
the Agent SDK with ``setting_sources=[]``.
"""

from devharness.mcp.base import CallResult, MCPClient

MCP_REASONING_TOOLS = [
    "reasoning_decision",
    "reasoning_reflection",
    "reasoning_meta",
]


class MCPReasoningClient(MCPClient):
    SERVER = "mcp-reasoning"

    def __init__(self, *, mcp_servers=None, **kwargs):
        super().__init__(
            server_name=self.SERVER,
            tools=MCP_REASONING_TOOLS,
            mcp_servers=mcp_servers or {self.SERVER: {}},
            **kwargs,
        )

    async def reasoning_decision(self, **params) -> CallResult:
        return await self.call("reasoning_decision", params)

    async def reasoning_reflection(self, **params) -> CallResult:
        return await self.call("reasoning_reflection", params)

    async def reasoning_meta(self, **params) -> CallResult:
        return await self.call("reasoning_meta", params)
