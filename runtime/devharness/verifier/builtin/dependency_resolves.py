"""dependency_resolves falsifier (B3.5).

A `dependency_bump` task's declared verification: the bump command applies, the manifest now
references the target version, the lockfile is regenerated to the target version, and the full
test suite still passes. Four axes, decision rule is code:
  - bump_applies: the bump command exits 0.
  - manifest_updates: the manifest references (dependency_name, target_version).
  - lockfile_updates: the lockfile references (dependency_name, target_version).
  - suite_passes: the full test suite exits 0.

A `pass_fail_command` / `test_command` that is sensitive to bytecode caches should bypass or
invalidate them (e.g. `python -B`); real test runners handle this themselves.
"""

import shlex
import subprocess
from pathlib import Path

from devharness.verifier.base import Verifier, VerifierFailed, VerifierOk
from devharness.verifier.builtin.test_suite import TestSuiteVerifier
from devharness.verifier.registry import register_verifier


def _as_list(command):
    return command if isinstance(command, list) else shlex.split(command)


def _run(command, cwd) -> int:
    return subprocess.run(_as_list(command), cwd=cwd, capture_output=True, text=True).returncode


def _read(cwd, rel_path) -> str | None:
    p = Path(cwd) / rel_path
    return p.read_text(encoding="utf-8") if p.exists() else None


def _references(content: str | None, dependency_name: str, target_version: str) -> bool:
    return content is not None and dependency_name in content and target_version in content


class DependencyResolvesVerifier(Verifier):
    name = "dependency_resolves"

    def __init__(self, test_suite=None):
        self._test_suite = test_suite or TestSuiteVerifier()

    async def verify(self, context: dict):
        cwd = context["cwd"]
        dependency_name = context["dependency_name"]
        target_version = context["target_version"]
        manifest_path = context["manifest_path"]
        lockfile_path = context["lockfile_path"]
        checkpoint = context.get("checkpoint")
        evidence = {
            "dependency_name": dependency_name, "target_version": target_version,
            "checkpoint_sha": getattr(checkpoint, "git_commit_sha", None),
        }

        # 0. fail closed on missing class fields (rev 0.3.70) — an empty bump_command CRASHED the
        # dispatch (subprocess of [''] → WinError 87, no terminal emitted, W re-crashed forever) and
        # empty name/version would VACUOUSLY PASS axes 2–3 ('' is a substring of everything). The
        # live trigger: the director's decomposition classes a dependency_bump correctly but leaves
        # the class fields empty; the driver derives them from the realized diff (class_commands.
        # derive_bump_fields) — reaching here empty means neither the plan nor the diff named them.
        missing = [k for k in ("dependency_name", "target_version", "bump_command", "manifest_path")
                   if not context.get(k)]
        if missing:
            evidence["missing_fields"] = missing
            return VerifierFailed(
                name=self.name,
                reason=f"class fields missing: {', '.join(missing)} — not declared on the task and "
                       "not derivable from the realized diff (no single manifest dependency change)",
                evidence=evidence)

        # 1. the bump command applies
        bump_rc = _run(context["bump_command"], cwd)
        evidence["bump_returncode"] = bump_rc
        if bump_rc != 0:
            return VerifierFailed(name=self.name, reason=f"bump_applies axis failed: bump command exited {bump_rc}", evidence=evidence)

        # 2. the manifest references the target version
        manifest = _read(cwd, manifest_path)
        evidence["manifest"] = (manifest or "")[-500:]
        if not _references(manifest, dependency_name, target_version):
            return VerifierFailed(name=self.name, reason=f"manifest_updates axis failed: {manifest_path} does not reference {dependency_name} {target_version}", evidence=evidence)

        # 3. the lockfile references the target version. SKIPPED when the project has no lockfile
        # (lockfile_path empty after worktree-presence derivation — e.g. a requirements-only
        # project): requiring one would make the class unusable there, and the prior behavior on
        # empty was a crash (_read of '' resolves to the worktree DIR). A project WHOSE lockfile
        # exists still faces this axis — derivation reads the worktree, not the diff, so an
        # un-regenerated lockfile fails here rather than silently skipping.
        if lockfile_path:
            lockfile = _read(cwd, lockfile_path)
            evidence["lockfile"] = (lockfile or "")[-500:]
            if not _references(lockfile, dependency_name, target_version):
                return VerifierFailed(name=self.name, reason=f"lockfile_updates axis failed: {lockfile_path} does not reference {dependency_name} {target_version}", evidence=evidence)
        else:
            evidence["lockfile_axis"] = "skipped: no lockfile in project"

        # 4. the full suite still passes
        suite = await self._test_suite.verify(context)
        evidence["suite"] = getattr(suite, "evidence", {})
        if isinstance(suite, VerifierFailed):
            return VerifierFailed(name=self.name, reason=f"suite_passes axis failed: {suite.reason}", evidence=evidence)
        return VerifierOk(name=self.name, evidence=evidence)


register_verifier("dependency_resolves", DependencyResolvesVerifier())
