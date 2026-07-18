"""B1.2: C10 — progress counts tool calls, ignores text output."""

import sys
from pathlib import Path
from types import SimpleNamespace

import claude_agent_sdk as sdk

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.roles.base import progress_from_messages


def test_zero_tool_calls_zero_progress():
    messages = [SimpleNamespace(content=[sdk.TextBlock(text="a"), sdk.TextBlock(text="b")])]
    assert progress_from_messages(messages) == 0


def test_n_tool_calls_n_progress():
    messages = [
        SimpleNamespace(
            content=[
                sdk.ToolUseBlock(id="1", name="mcp__parallax__elicit", input={}),
                sdk.TextBlock(text="some text"),
                sdk.ToolUseBlock(id="2", name="mcp__parallax__research", input={}),
            ]
        ),
        SimpleNamespace(content=[sdk.ToolUseBlock(id="3", name="mcp__parallax__diverge", input={})]),
    ]
    assert progress_from_messages(messages) == 3


def test_messages_without_content_ignored():
    messages = [SimpleNamespace(total_cost_usd=0.1), SimpleNamespace(content=None)]
    assert progress_from_messages(messages) == 0
