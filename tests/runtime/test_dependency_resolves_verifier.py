"""B3.5: DependencyResolvesVerifier — bump + manifest + lockfile + suite axes."""

import asyncio
import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import devharness.verifier.builtin  # noqa: F401
from devharness.verifier.base import VerifierFailed, VerifierOk
from devharness.verifier.builtin.dependency_resolves import DependencyResolvesVerifier
from devharness.verifier.registry import FALSIFIERS

BUMP = ["bump", "requests==2.31.0"]
SUITE = ["suite"]


def _proc(rc):
    return types.SimpleNamespace(returncode=rc, stdout="", stderr="")


def _mock_run(bump_rc, suite_rc):
    def run(cmd, *a, **k):
        if cmd == BUMP:
            return _proc(bump_rc)
        if cmd == SUITE:
            return _proc(suite_rc)
        return _proc(0)
    return run


def _repo(tmp_path, manifest="requests==2.31.0\n", lock="requests==2.31.0\n"):
    (tmp_path / "pyproject.toml").write_text(f"[project]\ndependencies = [\"{manifest.strip()}\"]\n")
    (tmp_path / "requirements.lock").write_text(lock)
    return tmp_path


def _ctx(tmp_path):
    return {"task_id": "t", "correlation_id": "c", "cwd": str(tmp_path),
            "checkpoint": types.SimpleNamespace(git_commit_sha="abc"),
            "bump_command": BUMP, "test_command": SUITE,
            "dependency_name": "requests", "target_version": "2.31.0",
            "manifest_path": "pyproject.toml", "lockfile_path": "requirements.lock"}


def test_registered():
    assert "dependency_resolves" in FALSIFIERS


def test_all_axes_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _mock_run(bump_rc=0, suite_rc=0))
    result = asyncio.run(DependencyResolvesVerifier().verify(_ctx(_repo(tmp_path))))
    assert isinstance(result, VerifierOk)


def test_bump_applies_axis(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _mock_run(bump_rc=1, suite_rc=0))  # bump fails
    result = asyncio.run(DependencyResolvesVerifier().verify(_ctx(_repo(tmp_path))))
    assert isinstance(result, VerifierFailed) and "bump_applies" in result.reason


def test_manifest_updates_axis(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _mock_run(bump_rc=0, suite_rc=0))
    repo = _repo(tmp_path, manifest="requests==2.30.0")  # wrong version in manifest
    result = asyncio.run(DependencyResolvesVerifier().verify(_ctx(repo)))
    assert isinstance(result, VerifierFailed) and "manifest_updates" in result.reason


def test_lockfile_updates_axis(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _mock_run(bump_rc=0, suite_rc=0))
    repo = _repo(tmp_path, lock="requests==2.30.0\n")  # lockfile not regenerated to target
    result = asyncio.run(DependencyResolvesVerifier().verify(_ctx(repo)))
    assert isinstance(result, VerifierFailed) and "lockfile_updates" in result.reason


def test_suite_passes_axis(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _mock_run(bump_rc=0, suite_rc=1))  # suite fails
    result = asyncio.run(DependencyResolvesVerifier().verify(_ctx(_repo(tmp_path))))
    assert isinstance(result, VerifierFailed) and "suite_passes" in result.reason


# --- rev 0.3.70: fail closed on empty class fields; skip the lockfile axis when none exists ---


def test_empty_class_fields_fail_closed_not_crash(tmp_path):
    # the live dependency_bump crash: a director-planned bump carried ALL class fields as "" —
    # subprocess of the empty bump_command died with OSError WinError 87, NO terminal emitted,
    # and W re-crashed forever. Empty fields are now a named VerifierFailed (normal reject flow).
    ctx = _ctx(_repo(tmp_path))
    for field in ("dependency_name", "target_version", "bump_command", "manifest_path"):
        ctx[field] = ""
    result = asyncio.run(DependencyResolvesVerifier().verify(ctx))
    assert isinstance(result, VerifierFailed)
    assert "class fields missing" in result.reason
    for field in ("dependency_name", "target_version", "bump_command", "manifest_path"):
        assert field in result.reason


def test_empty_name_version_cannot_vacuously_pass(monkeypatch, tmp_path):
    # '' is a substring of every manifest — axes 2-3 must never pass on empty name/version
    monkeypatch.setattr(subprocess, "run", _mock_run(bump_rc=0, suite_rc=0))
    ctx = _ctx(_repo(tmp_path))
    ctx["dependency_name"] = ""
    ctx["target_version"] = ""
    result = asyncio.run(DependencyResolvesVerifier().verify(ctx))
    assert isinstance(result, VerifierFailed) and "class fields missing" in result.reason


def test_lockfile_axis_skipped_when_project_has_none(monkeypatch, tmp_path):
    # a requirements-only project has no lockfile; empty lockfile_path used to crash
    # (_read('') resolves to the worktree DIR). The axis now skips with evidence, other axes hold.
    monkeypatch.setattr(subprocess, "run", _mock_run(bump_rc=0, suite_rc=0))
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
    ctx = _ctx(tmp_path)
    ctx["manifest_path"] = "requirements.txt"
    ctx["lockfile_path"] = ""
    result = asyncio.run(DependencyResolvesVerifier().verify(ctx))
    assert isinstance(result, VerifierOk)
    assert result.evidence["lockfile_axis"] == "skipped: no lockfile in project"
