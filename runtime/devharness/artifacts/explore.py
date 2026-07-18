"""Explore-pass artifact schema (B1.5).

A read-only structural snapshot of a repo: bounded file tree, dependency
manifests (with frameworks parsed from declared deps), test signatures, and CI
configs. Pure parse; never inferred, never executed.
"""

import msgspec

from devharness.artifacts.registry import register_artifact_schema


class FileTreeEntry(msgspec.Struct, frozen=True, kw_only=True):
    path: str  # relative path from repo_root (posix)
    kind: str  # file | directory
    depth: int
    schema_version: int = 1


class DependencyManifest(msgspec.Struct, frozen=True, kw_only=True):
    path: str  # relative path of the manifest file
    manifest_kind: str  # pyproject | package_json | cargo | requirements | gemfile | go_mod
    detected_frameworks: list[str]  # framework names parsed from declared dependencies
    schema_version: int = 1


class TestSignature(msgspec.Struct, frozen=True, kw_only=True):
    path: str  # relative path to the test dir or root config file
    test_framework: str  # pytest | vitest | cargo_test | go_test | rspec | jest | unknown
    schema_version: int = 1


class CIConfig(msgspec.Struct, frozen=True, kw_only=True):
    path: str  # relative path to the CI config
    ci_kind: str  # github_actions | gitlab_ci | circleci | jenkins
    schema_version: int = 1


class ExplorePassArtifact(msgspec.Struct, frozen=True, kw_only=True):
    explore_pass_id: str
    repo_root: str  # absolute path of the repo analyzed
    file_tree: list[FileTreeEntry]  # depth-bounded
    dependency_manifests: list[DependencyManifest]
    test_signatures: list[TestSignature]
    ci_configs: list[CIConfig]
    correlation_id: str
    created_at_millis: int
    schema_version: int = 1


register_artifact_schema("explore_pass", ExplorePassArtifact)
