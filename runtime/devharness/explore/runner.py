"""Explore-pass runner (B1.5). Read-only structural analysis of a repo.

Walks a bounded file tree, detects + parses dependency manifests, and identifies
test/CI signatures. Pure parsing: no inference, no execution, no writes to the
analyzed repo. run_and_emit persists the artifact and records explore_pass_completed.
"""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

import msgspec

from devharness.artifacts.explore import (
    CIConfig,
    DependencyManifest,
    ExplorePassArtifact,
    FileTreeEntry,
    TestSignature,
)
from devharness.events.registry import ExplorePassCompleted
from devharness.explore.parsers import (
    cargo,
    gemfile,
    go_mod,
    package_json,
    pyproject,
    requirements,
)

NOISE_DIRS = {".git", "node_modules", "target", "__pycache__", ".venv"}

MANIFEST_KINDS = {
    "pyproject.toml": "pyproject",
    "package.json": "package_json",
    "Cargo.toml": "cargo",
    "requirements.txt": "requirements",
    "Gemfile": "gemfile",
    "go.mod": "go_mod",
}

_PARSERS = {
    "pyproject": pyproject.parse,
    "package_json": package_json.parse,
    "cargo": cargo.parse,
    "requirements": requirements.parse,
    "gemfile": gemfile.parse,
    "go_mod": go_mod.parse,
}

# Framework names recognized in declared dependencies (exact, case-insensitive).
FRAMEWORK_NAMES = {
    "pytest", "fastapi", "django", "flask", "starlette", "pydantic", "sqlalchemy",
    "celery", "uvicorn", "react", "vue", "svelte", "express", "next", "vitest",
    "jest", "webpack", "vite", "rails", "sinatra", "rspec", "axum", "tokio",
    "actix-web", "rocket", "serde", "gin", "echo", "fiber",
}

TEST_DIRS = {"tests", "test", "spec"}


def detect_frameworks(dependency_names) -> list[str]:
    return sorted({name for name in dependency_names if name.lower() in FRAMEWORK_NAMES})


def _file_tree(root: Path, max_depth: int) -> list[FileTreeEntry]:
    entries: list[FileTreeEntry] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dir_depth = 0 if str(rel_dir) == "." else len(rel_dir.parts)
        dirnames[:] = sorted(d for d in dirnames if d not in NOISE_DIRS)
        child_depth = dir_depth + 1
        for name in dirnames:
            rel = name if str(rel_dir) == "." else (rel_dir / name).as_posix()
            if child_depth <= max_depth:
                entries.append(FileTreeEntry(path=str(rel), kind="directory", depth=child_depth))
        for name in sorted(filenames):
            rel = name if str(rel_dir) == "." else (rel_dir / name).as_posix()
            if child_depth <= max_depth:
                entries.append(FileTreeEntry(path=str(rel), kind="file", depth=child_depth))
        if child_depth >= max_depth:
            dirnames[:] = []  # do not descend past the bound
    return entries


def _dependency_manifests(root: Path, file_tree) -> tuple[list[DependencyManifest], set]:
    manifests: list[DependencyManifest] = []
    kinds: set = set()
    for entry in file_tree:
        if entry.kind != "file":
            continue
        name = entry.path.rsplit("/", 1)[-1]
        kind = MANIFEST_KINDS.get(name)
        if kind is None:
            continue
        deps = _PARSERS[kind](str(root / entry.path))
        manifests.append(
            DependencyManifest(path=entry.path, manifest_kind=kind, detected_frameworks=detect_frameworks(deps))
        )
        kinds.add(kind)
    return manifests, kinds


def _test_signatures(file_tree, manifest_kinds) -> list[TestSignature]:
    signatures: list[TestSignature] = []
    seen: set = set()

    def add(path, framework):
        key = (path, framework)
        if key not in seen:
            seen.add(key)
            signatures.append(TestSignature(path=path, test_framework=framework))

    for entry in file_tree:
        name = entry.path.rsplit("/", 1)[-1]
        if entry.kind == "file":
            if name == "pytest.ini":
                add(entry.path, "pytest")
            elif name.startswith("vitest.config."):
                add(entry.path, "vitest")
            elif name.startswith("jest.config."):
                add(entry.path, "jest")
        elif name in TEST_DIRS:
            add(entry.path, "rspec" if name == "spec" else "pytest")
    if "cargo" in manifest_kinds:
        add("Cargo.toml", "cargo_test")
    if "go_mod" in manifest_kinds:
        add("go.mod", "go_test")
    return signatures


def _ci_configs(file_tree) -> list[CIConfig]:
    configs: list[CIConfig] = []
    for entry in file_tree:
        path = entry.path
        if entry.kind == "file" and path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml")):
            configs.append(CIConfig(path=path, ci_kind="github_actions"))
        elif path == ".gitlab-ci.yml":
            configs.append(CIConfig(path=path, ci_kind="gitlab_ci"))
        elif entry.kind == "file" and path.startswith(".circleci/"):
            configs.append(CIConfig(path=path, ci_kind="circleci"))
        elif path == "Jenkinsfile":
            configs.append(CIConfig(path=path, ci_kind="jenkins"))
    return configs


def run(repo_root: str, correlation_id: str, max_depth: int = 5) -> ExplorePassArtifact:
    root = Path(repo_root)
    file_tree = _file_tree(root, max_depth)
    manifests, manifest_kinds = _dependency_manifests(root, file_tree)
    return ExplorePassArtifact(
        explore_pass_id=uuid4().hex,
        repo_root=str(root.resolve()),
        file_tree=file_tree,
        dependency_manifests=manifests,
        test_signatures=_test_signatures(file_tree, manifest_kinds),
        ci_configs=_ci_configs(file_tree),
        correlation_id=correlation_id,
        created_at_millis=int(time.time() * 1000),
    )


def run_and_emit(repo_root: str, correlation_id: str, event_bus, conn) -> str:
    artifact = run(repo_root, correlation_id)
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'explore_pass', ?, ?, ?, ?, 0)",
        (artifact.explore_pass_id, artifact.schema_version, json.dumps(msgspec.to_builtins(artifact)), correlation_id, artifact.created_at_millis),
    )
    conn.commit()
    event_bus.emit_sync(
        "explore_pass_completed",
        msgspec.to_builtins(
            ExplorePassCompleted(
                repo_path=artifact.repo_root,
                summary_ref=artifact.explore_pass_id,
                file_count=len(artifact.file_tree),
                manifest_count=len(artifact.dependency_manifests),
                test_count=len(artifact.test_signatures),
                ci_count=len(artifact.ci_configs),
            )
        ),
        correlation_id=correlation_id,
    )
    return artifact.explore_pass_id
