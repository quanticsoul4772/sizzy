"""B4.3: an OSS (is_oss=True) feature task routes through the four real OSS gates (workflow_guard,
secret_guard path+content, scope_guard, sandbox); override / WSL-available allow; BUILD gates fire."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401  (registers feature_spec_claim)
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
    }
    base.update(overrides)
    return base


def test_sandbox_denies_without_override_or_wsl(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    results = run_admission_gates("feature", _ctx(), is_oss=True)
    assert admission_denied(results) == "sandbox"


def test_clean_dispatch_with_sandbox_override(monkeypatch):
    # the CI scenario: no real sandbox on the runner -> override lets the OSS dispatch through
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    results = run_admission_gates("feature", _ctx(sandbox_override=True), is_oss=True)
    assert admission_denied(results) is None


def test_clean_dispatch_with_wsl_available(monkeypatch):
    # the dev-box scenario: WSL present -> sandbox passes without an override
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: True)
    results = run_admission_gates("feature", _ctx(), is_oss=True)
    assert admission_denied(results) is None


def test_secret_path_axis_denies_even_with_sandbox_override(monkeypatch):
    # the secret_guard path axis fires before sandbox in the overlay order
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    results = run_admission_gates("feature", _ctx(touched_paths=[".env"], sandbox_override=True), is_oss=True)
    assert admission_denied(results) == "secret_guard"


def test_build_gate_still_fires_no_regression(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    # an out-of-scope write is still denied by the B2.1 scope_gate even on a non-OSS task
    results = run_admission_gates("feature", _ctx(scope_boundary=["src/**"], touched_paths=["secrets/leak.txt"]), is_oss=False)
    assert admission_denied(results) == "scope_gate"
    assert "sandbox" not in {n for n, _ in results}  # OSS gates absent when is_oss=False
