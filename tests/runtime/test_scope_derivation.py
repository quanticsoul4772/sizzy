"""B3.1: derive_scope_boundary from an explore-pass + task targets."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.explore import DependencyManifest, ExplorePassArtifact, FileTreeEntry
from devharness.artifacts.explore import TestSignature as _TestSignature  # aliased: avoid pytest collecting it
from devharness.explore.scope_derivation import derive_scope_boundary


def _artifact():
    return ExplorePassArtifact(
        explore_pass_id="e1", repo_root="/r",
        file_tree=[FileTreeEntry(path="src/app/main.py", kind="file", depth=2)],
        dependency_manifests=[DependencyManifest(path="pyproject.toml", manifest_kind="pyproject", detected_frameworks=["pytest"])],
        test_signatures=[_TestSignature(path="src/app/tests", test_framework="pytest"), _TestSignature(path="other/tests", test_framework="pytest")],
        ci_configs=[], correlation_id="c", created_at_millis=1,
    )


def test_covers_target_and_surrounding_dir():
    globs = derive_scope_boundary(_artifact(), ["src/app/main.py"])
    assert "src/app/main.py" in globs       # the target itself
    assert "src/app/**" in globs            # surrounding directory


def test_includes_intersecting_test_dir_only():
    globs = derive_scope_boundary(_artifact(), ["src/app/main.py"])
    # the test dir under the target's tree is included
    assert "src/app/tests" in globs or "src/app/tests/**" in globs
    # an unrelated top-level test dir is not pulled in
    assert "other/tests" not in globs and "other/tests/**" not in globs


def test_dependency_bump_includes_manifests():
    globs = derive_scope_boundary(_artifact(), ["src/app/main.py"], task_class="dependency_bump")
    assert "pyproject.toml" in globs


def test_non_dependency_bump_excludes_manifests():
    globs = derive_scope_boundary(_artifact(), ["src/app/main.py"], task_class="feature")
    assert "pyproject.toml" not in globs
