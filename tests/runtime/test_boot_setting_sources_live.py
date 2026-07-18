"""#C5/#H8: the commitment-3 boot check enforces the LIVE setting_sources=[] posture.

It used to iterate only the legacy role-spec registry, which the current architecture leaves empty
(roles grew their own run() instead of spawn_role), so it was vacuously true. It now also asserts the
abstract role base and the MCP client every real role drives through — catching a real regression
where agent sessions would inherit filesystem settings.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.boot import BootError, check_setting_sources_empty
from devharness.mcp.base import MCPClient
from devharness.roles.base import AgentRole


def test_passes_with_the_live_empty_posture():
    assert check_setting_sources_empty() is True


def test_fails_if_the_role_base_inherits_settings(monkeypatch):
    monkeypatch.setattr(AgentRole, "setting_sources", ["project"])
    with pytest.raises(BootError, match="commitment 3"):
        check_setting_sources_empty()


def test_fails_if_the_mcp_client_inherits_settings(monkeypatch):
    monkeypatch.setattr(MCPClient, "SETTING_SOURCES", ["user"])
    with pytest.raises(BootError, match="commitment 3"):
        check_setting_sources_empty()
