"""B4.0: is_oss=True layers the four §S5 OSS gates onto the BUILD class's gate profile."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.task_classes.gate_binding import OSS_GATES, required_gates_for


def test_oss_layers_onto_build_profile():
    base = required_gates_for("feature", is_oss=False)
    layered = required_gates_for("feature", is_oss=True)
    assert layered == base + ["workflow_guard", "secret_guard", "scope_guard", "sandbox"]
    assert OSS_GATES == ["workflow_guard", "secret_guard", "scope_guard", "sandbox"]


def test_non_oss_unchanged_for_all_build_classes():
    for tc in ("feature", "bugfix", "refactor", "dependency_bump"):
        assert all(g not in required_gates_for(tc, is_oss=False) for g in OSS_GATES)
        assert required_gates_for(tc, is_oss=True) == required_gates_for(tc, is_oss=False) + OSS_GATES


def test_default_is_oss_false():
    # the additive default keeps the B3 behaviour: required_gates_for(tc) == the BUILD profile
    assert required_gates_for("bugfix") == required_gates_for("bugfix", is_oss=False)
