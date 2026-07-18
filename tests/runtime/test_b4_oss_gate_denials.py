"""B4.8 acceptance: each of the four §S5 OSS gates denies its known-bad in an OSS admission context."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401
from devharness.sandbox import registry as sandbox_registry
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_classes.gate_binding import admission_denied, run_admission_gates

GH = "ghp_" + "a" * 36


def setup_module():
    register_builtin_task_classes()


def _ctx(**overrides):
    base = {
        "planned_task": types.SimpleNamespace(task_class="feature", scope_boundary=["**"], verifier_ref="feature_spec_claim"),
        "task_class": "feature", "scope_boundary": ["**"], "touched_paths": ["src/app.py"],
        "command_string": "", "verifier_ref": "feature_spec_claim", "diff_content": "",
        "sandbox_override": True,  # isolate non-sandbox gates; the sandbox test drops this
    }
    base.update(overrides)
    return base


def test_workflow_guard_denies():
    r = run_admission_gates("feature", _ctx(touched_paths=[".github/workflows/ci.yml"]), is_oss=True)
    assert admission_denied(r) == "workflow_guard"


def test_secret_guard_path_axis_denies():
    r = run_admission_gates("feature", _ctx(touched_paths=[".env"]), is_oss=True)
    assert admission_denied(r) == "secret_guard"


def test_secret_guard_content_axis_denies():
    r = run_admission_gates("feature", _ctx(diff_content=f"+token = {GH}"), is_oss=True)
    assert admission_denied(r) == "secret_guard"


def test_scope_guard_loc_denies():
    r = run_admission_gates("feature", _ctx(diff_content="\n".join("+l" for _ in range(501))), is_oss=True)
    assert admission_denied(r) == "scope_guard"


def test_sandbox_denies_without_override(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    ctx = _ctx()
    del ctx["sandbox_override"]
    r = run_admission_gates("feature", ctx, is_oss=True)
    assert admission_denied(r) == "sandbox"


def test_sandbox_override_allows(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    r = run_admission_gates("feature", _ctx(), is_oss=True)  # sandbox_override=True in base
    assert admission_denied(r) is None
