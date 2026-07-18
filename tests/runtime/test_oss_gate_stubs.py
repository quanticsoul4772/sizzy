"""B4.0/B4.3: the four OSS gates are registered; after B4.3 all four enforce (no stubs remain)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.task_classes.gate_binding  # noqa: F401  (imports the OSS gate modules for registration)
from devharness.gates.registry import GATES

OSS_GATE_NAMES = ["workflow_guard", "secret_guard", "scope_guard", "sandbox"]


def test_four_oss_gates_registered():
    for name in OSS_GATE_NAMES:
        assert name in GATES


def test_all_four_oss_gates_enforce_after_b4_3():
    # B4.2 graduated workflow/secret/scope; B4.3 graduated sandbox -> none is a not-yet-implemented stub
    from devharness.gates.base import GateDeny
    assert isinstance(GATES["workflow_guard"].check({"touched_paths": [".github/workflows/ci.yml"]}), GateDeny)
    assert isinstance(GATES["secret_guard"].check({"diff_content": "+t = ghp_" + "a" * 36}), GateDeny)
    assert isinstance(GATES["scope_guard"].check({"diff_content": "\n".join("+l" for _ in range(501))}), GateDeny)
    assert isinstance(GATES["sandbox"].check({"sandbox_launcher_preferred": "mock"}), GateDeny)


def test_scope_guard_distinct_from_scope_gate():
    # the §S5 scope_guard (cumulative-LOC, stubbed) is a different gate from the B2.1 scope_gate
    assert "scope_guard" in GATES and "scope_gate" in GATES
    assert GATES["scope_guard"] is not GATES["scope_gate"]
