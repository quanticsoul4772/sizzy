"""B2.5: Invariant 2 — the reviewer has zero write tools across all allowed servers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.call_class import classify
from devharness.roles.reviewer import REVIEWER_ACI_TOOLS, ReviewerRole, reviewer_tool_inventory


def test_inv2_reviewer_zero_write_tools():
    inv = reviewer_tool_inventory()
    # nothing classifies as mutation
    assert all(classify(tool) != "mutation" for tool in inv)
    # no raw write tools
    assert not any(t in inv for t in ("Edit", "Write", "Bash", "NotebookEdit"))
    # no ACI write/shell actions
    assert not any("write_file" in t or "append_to_file" in t or "run_command" in t for t in inv)


def test_reviewer_aci_tools_are_read_only():
    # the only ACI tools the reviewer carries are read + run_tests
    assert set(REVIEWER_ACI_TOOLS) == {"open_file", "read_range", "run_tests"}
    assert all(classify(f"mcp__devharness-aci__{t}") != "mutation" for t in REVIEWER_ACI_TOOLS)


def test_allowed_servers():
    assert ReviewerRole.ALLOWED_MCP_SERVERS == ["parallax", "devharness-aci"]
