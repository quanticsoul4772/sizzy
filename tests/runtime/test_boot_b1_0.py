"""B1.0 / C3 (constitution v0.2.0): the single graduated C3 boot check is registered + passes for the live
`setting_sources=[]` posture. The per-role-budget claim (`check_role_context_budget_declared`) was retired
in the v0.2.0 amendment; the setting-sources fail-closed path is covered by test_boot_setting_sources_live."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot


def test_setting_sources_is_the_only_c3_check():
    names = boot.registered_check_names()
    assert "check_setting_sources_empty" in names
    assert boot.REQUIRED_GATES["check_setting_sources_empty"] == "C3"
    assert "check_role_context_budget_declared" not in names  # retired in v0.2.0
    assert boot.CONSTITUTION_CLAIMS["C3"] == ["check_setting_sources_empty"]


def test_setting_sources_check_passes_for_the_live_posture():
    # AgentRole.setting_sources == [] and MCPClient.SETTING_SOURCES == [] in production
    assert boot.check_setting_sources_empty() is True
