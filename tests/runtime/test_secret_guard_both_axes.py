"""B4.2-reconciliation: secret_guard defense in depth — both axes, independent overrides."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.gates.base import GateDeny, GateOk
from devharness.gates.secret_guard import SecretGuard

GH = "ghp_" + "a" * 36


def _check(**ctx):
    return SecretGuard().check(ctx)


def test_both_axes_trigger():
    r = _check(touched_paths=[".env"], diff_content=f"+t = {GH}")
    assert isinstance(r, GateDeny)
    assert r.evidence["axes_triggered"] == ["path", "content"]
    assert r.evidence["matched_paths"] == [".env"] and r.evidence["matched_patterns"] == ["github_token"]


def test_both_axes_overridden_passes():
    r = _check(touched_paths=[".env"], diff_content=f"+t = {GH}",
               secret_guard_path_override=True, secret_guard_content_override=True)
    assert isinstance(r, GateOk) and r.reason == "secret_detected_with_override"


def test_path_overridden_but_content_triggers_still_denies():
    # a contributor must evade BOTH axes — overriding only the path axis leaves content denying
    r = _check(touched_paths=[".env"], diff_content=f"+t = {GH}", secret_guard_path_override=True)
    assert isinstance(r, GateDeny) and r.evidence["axes_triggered"] == ["content"]


def test_content_overridden_but_path_triggers_still_denies():
    r = _check(touched_paths=[".env"], diff_content=f"+t = {GH}", secret_guard_content_override=True)
    assert isinstance(r, GateDeny) and r.evidence["axes_triggered"] == ["path"]
