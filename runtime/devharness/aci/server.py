"""ACI MCP server descriptor (B2.3).

`devharness-aci` is the in-runtime MCP server exposing the editor / shell / test-runner
ACI surfaces as MCP tools. The developer's Agent SDK worker connects to it alongside
parallax and mcp-reasoning. B2.3 builds the descriptor (tool names + bound handlers);
the live Agent-SDK MCP binding is wired when the developer runs against a real SDK in
B2.7 dispatch.
"""

ACI_SERVER_NAME = "devharness-aci"

# editor read + write actions, shell, test runner
ACI_TOOLS = [
    "open_file",
    "read_range",
    "write_file",
    "append_to_file",
    "run_command",
    "run_tests",
]


def aci_tool_names() -> list[str]:
    return [f"mcp__{ACI_SERVER_NAME}__{tool}" for tool in ACI_TOOLS]


def build_aci_server(editor, shell, test_runner) -> dict:
    """Bind the ACI actions to their tool names for one worktree/task (descriptor form)."""
    return {
        "name": ACI_SERVER_NAME,
        "tools": {
            "open_file": editor.open_file,
            "read_range": editor.read_range,
            "write_file": editor.write_file,
            "append_to_file": editor.append_to_file,
            "run_command": shell.run_command,
            "run_tests": test_runner.run_tests,
        },
    }


def call_tool(aci_server: dict, tool_name: str, **kwargs):
    """Invoke a bound ACI tool by name (the live binding: tool calls reach the surfaces)."""
    handler = aci_server["tools"].get(tool_name)
    if handler is None:
        raise KeyError(f"{tool_name} is not an ACI tool")
    return handler(**kwargs)


def _pred(args) -> float:
    """The worker's predicted_success from an ACI write tool-call, clamped to [0,1]; 0.5 if
    absent/invalid (#M4). The live write path emitted a constant 0.5 because the MCP write tools
    dropped this — making the Brier calibration signal a constant. The editor already records it."""
    try:
        return min(1.0, max(0.0, float(args.get("predicted_success", 0.5))))
    except (TypeError, ValueError):
        return 0.5


# Full JSON schema (not the {name: type} shorthand, which marks every key required): predicted_success
# is OPTIONAL so a worker that omits it still writes — `_pred` defaults to 0.5. (#M4/#7 review fix.)
def _write_schema(verb: str) -> dict:
    return {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "predicted_success": {"type": "number", "description":
                f"your probability (0.0-1.0) that this {verb} is in-scope and correct — calibrates SC-5 trust"},
        },
        "required": ["path", "content"],
    }


def make_aci_mcp_server(editor, shell, test_runner):
    """Build the live in-runtime Agent-SDK MCP server (B2.7).

    The director spawns the developer with this server in its MCP config; the worker's
    tool calls hit the live editor/shell/test_runner surfaces.
    """
    from claude_agent_sdk import create_sdk_mcp_server, tool

    def _ok(text):
        return {"content": [{"type": "text", "text": text}]}

    @tool("open_file", "Read a file in the worktree", {"path": str})
    async def open_file(args):
        return _ok(editor.open_file(args["path"]))

    @tool("read_range", "Read a line range from a file", {"path": str, "start": int, "end": int})
    async def read_range(args):
        return _ok(editor.read_range(args["path"], args["start"], args["end"]))

    @tool("write_file", "Write a file (gate-checked vs scope). Set predicted_success to your probability "
          "(0.0-1.0) that this write is in-scope and correct — it calibrates the trust signal (SC-5).",
          _write_schema("write"))
    async def write_file(args):
        editor.write_file(args["path"], args["content"], predicted_success=_pred(args))
        return _ok("written")

    @tool("append_to_file", "Append to a file (gate-checked vs scope). Set predicted_success to your "
          "probability (0.0-1.0) that this write is in-scope and correct — it calibrates SC-5.",
          _write_schema("append"))
    async def append_to_file(args):
        editor.append_to_file(args["path"], args["content"], predicted_success=_pred(args))
        return _ok("appended")

    @tool("run_command", "Run a shell command (destructive-gate enforced)", {"command_string": str})
    async def run_command(args):
        return _ok(str(shell.run_command(args["command_string"])))

    @tool("run_tests", "Run the configured test suite", {})
    async def run_tests(args):
        return _ok(str(test_runner.run_tests()))

    return create_sdk_mcp_server(
        ACI_SERVER_NAME, "1.0.0",
        [open_file, read_range, write_file, append_to_file, run_command, run_tests],
    )
