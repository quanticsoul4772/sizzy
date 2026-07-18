"""B4.2: an OSS (is_oss=True) feature task routes through the BUILD profile + the three real
OSS gates; each deny scenario fires, overrides allow, and the BUILD gates still enforce."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers feature_spec_claim)
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_classes.gate_binding import admission_denied, required_gates_for, run_admission_gates

GH = "ghp_" + "a" * 36


def _ctx(**overrides):
    base = {
        "planned_task": types.SimpleNamespace(task_class="feature", scope_boundary=["**"], verifier_ref="feature_spec_claim"),
        "task_class": "feature", "scope_boundary": ["**"], "touched_paths": ["src/app.py"],
        "command_string": "", "verifier_ref": "feature_spec_claim", "diff_content": "",
        # B4.3: the sandbox gate now enforces; this suite targets the path/LOC gates, so override
        # sandbox to keep those assertions focused (the sandbox gate has its own B4.3 e2e).
        "sandbox_override": True,
    }
    base.update(overrides)
    return base


def setup_module():
    register_builtin_task_classes()


def test_oss_overlay_includes_build_and_oss_gates():
    gates = required_gates_for("feature", is_oss=True)
    assert {"scope_gate", "blast_radius_gate", "destructive_command_gate", "verifier_attached_gate"} <= set(gates)
    assert gates[-4:] == ["workflow_guard", "secret_guard", "scope_guard", "sandbox"]


def test_clean_oss_task_passes():
    results = run_admission_gates("feature", _ctx(), is_oss=True)
    assert admission_denied(results) is None


def test_workflow_modifying_denies():
    results = run_admission_gates("feature", _ctx(touched_paths=[".github/workflows/ci.yml"]), is_oss=True)
    assert admission_denied(results) == "workflow_guard"


def test_secret_leaking_denies():
    results = run_admission_gates("feature", _ctx(diff_content=f"+token = {GH}"), is_oss=True)
    assert admission_denied(results) == "secret_guard"


def test_over_loc_denies():
    results = run_admission_gates("feature", _ctx(diff_content="\n".join("+l" for _ in range(501))), is_oss=True)
    assert admission_denied(results) == "scope_guard"


def test_overrides_allow_each_gate():
    wf = run_admission_gates("feature", _ctx(touched_paths=[".github/workflows/ci.yml"], workflow_guard_override=True), is_oss=True)
    assert admission_denied(wf) is None
    sec = run_admission_gates("feature", _ctx(diff_content=f"+t = {GH}", secret_guard_content_override=True), is_oss=True)
    assert admission_denied(sec) is None
    loc = run_admission_gates("feature", _ctx(diff_content="\n".join("+l" for _ in range(501)), scope_guard_override=True), is_oss=True)
    assert admission_denied(loc) is None


def test_build_gate_still_fires_no_regression():
    # an out-of-scope write is still denied by the B2.1 scope_gate even on a non-OSS task
    results = run_admission_gates("feature", _ctx(scope_boundary=["src/**"], touched_paths=["secrets/leak.txt"]), is_oss=False)
    assert admission_denied(results) == "scope_gate"
    # and the OSS gates are absent when is_oss=False
    assert all(g not in {n for n, _ in results} for g in ("workflow_guard", "secret_guard", "scope_guard"))
