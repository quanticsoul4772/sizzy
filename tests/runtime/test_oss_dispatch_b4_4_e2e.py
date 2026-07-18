"""B4.4 e2e: OSS task gets a fork-branch worktree off target_branch; the OSS-tightened scope is
enforced by the B2.1 scope_gate (out-of-scope + /etc escapes denied); non-OSS dispatch unaffected."""

import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401
from devharness.oss.scope_oss import tighten_oss_scope
from devharness.sandbox import registry as sandbox_registry
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_classes.gate_binding import admission_denied, run_admission_gates
from devharness.worktree.isolate import create_worktree, discard_worktree

REPO = "octo/widget"


def setup_module():
    register_builtin_task_classes()


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _upstream(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-b", "main")
    (repo / "README.md").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "release")
    return repo


def test_fork_branch_worktree_off_target(tmp_path):
    repo = _upstream(tmp_path)
    wt = create_worktree("oss-e2e", str(repo), oss_task_id="oss-e2e", oss_target_branch="release")
    try:
        assert wt.fork_branch == "devharness-oss/oss-e2e"
        head = subprocess.run(["git", "-C", wt.path, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
        assert head == "devharness-oss/oss-e2e"
    finally:
        discard_worktree(wt)
        _git(repo, "branch", "-D", "devharness-oss/oss-e2e")


def _ctx(scope, touched, **extra):
    base = {
        "planned_task": types.SimpleNamespace(task_class="feature", scope_boundary=scope, verifier_ref="feature_spec_claim"),
        "task_class": "feature", "scope_boundary": scope, "touched_paths": touched,
        "command_string": "", "verifier_ref": "feature_spec_claim", "diff_content": "",
        "sandbox_override": True,
    }
    base.update(extra)
    return base


def _tightened():
    # requested scope includes an escape; tightening drops it, leaving the in-repo globs
    return tighten_oss_scope(["src/**", "../escape/**"], REPO)  # -> ["src/**"]


def test_out_of_scope_write_denied(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    scope = _tightened()
    results = run_admission_gates("feature", _ctx(scope, ["docs/secret.md"]), is_oss=True)
    assert admission_denied(results) == "scope_gate"


def test_etc_passwd_write_denied(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    scope = _tightened()
    assert "../escape/**" not in scope  # the escape never made it into the boundary
    results = run_admission_gates("feature", _ctx(scope, ["/etc/passwd"]), is_oss=True)
    assert admission_denied(results) == "scope_gate"


def test_in_scope_oss_write_passes(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    results = run_admission_gates("feature", _ctx(_tightened(), ["src/app.py"]), is_oss=True)
    assert admission_denied(results) is None


def test_non_oss_dispatch_unaffected(monkeypatch):
    monkeypatch.setattr(sandbox_registry, "detect_wsl", lambda: False)
    # a non-OSS feature with an in-scope write passes; no OSS gates run
    results = run_admission_gates("feature", _ctx(["src/**"], ["src/app.py"]), is_oss=False)
    assert admission_denied(results) is None
    assert all(g not in {n for n, _ in results} for g in ("workflow_guard", "secret_guard", "scope_guard", "sandbox"))
