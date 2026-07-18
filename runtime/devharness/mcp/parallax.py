"""parallax MCP client wrapper (B1.0).

Wraps the parallax server's tools, each routed through the Agent SDK with
``setting_sources=[]``. The ``mcp_servers`` config is injected by the runtime;
the placeholder default lets the substrate construct without a live server (the
real config lands when roles run in B1.2).
"""

from devharness.mcp.base import CallResult, MCPClient

PARALLAX_TOOLS = [
    "decide",
    "elicit",
    "verify",
    "check",
    "unstick",
    "research",
    "save",
    "recall",
    "forget",
    "diverge",
    "grounded_verify",
]


class ParallaxClient(MCPClient):
    SERVER = "parallax"

    def __init__(self, *, mcp_servers=None, **kwargs):
        super().__init__(
            server_name=self.SERVER,
            tools=PARALLAX_TOOLS,
            mcp_servers=mcp_servers or {self.SERVER: {}},
            **kwargs,
        )

    async def decide(self, **params) -> CallResult:
        return await self.call("decide", params)

    async def elicit(self, **params) -> CallResult:
        return await self.call("elicit", params)

    async def verify(self, **params) -> CallResult:
        return await self.call("verify", params)

    async def check(self, **params) -> CallResult:
        return await self.call("check", params)

    async def unstick(self, **params) -> CallResult:
        return await self.call("unstick", params)

    async def research(self, **params) -> CallResult:
        return await self.call("research", params)

    async def save(self, **params) -> CallResult:
        return await self.call("save", params)

    async def recall(self, **params) -> CallResult:
        return await self.call("recall", params)

    async def forget(self, **params) -> CallResult:
        return await self.call("forget", params)

    async def diverge(self, **params) -> CallResult:
        return await self.call("diverge", params)

    async def grounded_verify(self, **params) -> CallResult:
        return await self.call("grounded_verify", params)
