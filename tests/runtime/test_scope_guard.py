"""B4.2: scope_guard — cumulative net-LOC over limit denies; configurable; override allows."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.gates.base import GateDeny, GateOk
from devharness.gates.scope_guard import ScopeGuard, cumulative_churn_loc


def _diff(added, removed=0):
    return "\n".join(["+a"] * added + ["-r"] * removed)


def test_churn_loc_added_plus_removed():
    # F6: churn is added PLUS removed (review burden = every changed line, not the net)
    assert cumulative_churn_loc(_diff(10, 3)) == 13
    # headers + binaries are ignored; one +added + one -removed body line = churn 2
    diff = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n+added\n-removed\nBinary files a/i b/i differ"
    assert cumulative_churn_loc(diff) == 2
    # a delete-and-readd that nets ~0 no longer games the cap
    assert cumulative_churn_loc(_diff(300, 300)) == 600


def test_limit_boundary():
    assert isinstance(ScopeGuard().check({"diff_content": _diff(500)}), GateOk)  # exactly at limit passes
    r = ScopeGuard().check({"diff_content": _diff(501)})
    assert isinstance(r, GateDeny) and r.evidence == {"cumulative_churn_loc": 501, "limit": 500}


def test_configurable_limit_via_context():
    assert isinstance(ScopeGuard().check({"diff_content": _diff(60), "scope_guard_limit": 50}), GateDeny)
    assert isinstance(ScopeGuard().check({"diff_content": _diff(60), "scope_guard_limit": 100}), GateOk)


def test_configurable_limit_via_env(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OSS_SCOPE_LOC_LIMIT", "10")
    assert isinstance(ScopeGuard().check({"diff_content": _diff(11)}), GateDeny)


def test_override_allows():
    r = ScopeGuard().check({"diff_content": _diff(501), "scope_guard_override": True})
    assert isinstance(r, GateOk) and r.reason == "loc_over_limit_with_override"
