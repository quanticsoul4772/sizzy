"""Explore-pass -> scope_boundary derivation (B3.1).

For an existing-repo task, the director derives the task's scope_boundary from the B1.5
explore-pass (the repo's structure) plus the paths the task expects to touch. The result is
a list of globs the scope gate (B2.1) enforces: the targets, their surrounding directories,
intersecting test directories, and — for dependency_bump — the dependency manifests.
"""

import posixpath

# manifest filenames whose enclosing change a dependency_bump must be allowed to touch
_MANIFEST_BASENAMES = {
    "pyproject.toml", "package.json", "package-lock.json", "cargo.toml", "cargo.lock",
    "requirements.txt", "gemfile", "gemfile.lock", "go.mod", "go.sum",
}


def _dir_of(path: str) -> str:
    return posixpath.dirname(path.replace("\\", "/"))


def _intersects(sig_path: str, target_dirs: set) -> bool:
    sig_dir = _dir_of(sig_path) or sig_path
    for td in target_dirs:
        if not td:
            continue
        # the test path is under a target dir, or a target is under the test path, or they share a top segment
        if sig_dir == td or sig_dir.startswith(td + "/") or td.startswith(sig_dir + "/"):
            return True
        if sig_dir.split("/", 1)[0] == td.split("/", 1)[0]:
            return True
    return False


def derive_scope_boundary(explore_pass_artifact, task_target_paths, task_class=None) -> list[str]:
    """Globs covering the task's targets, their directories, intersecting tests, and (for
    dependency_bump) the dependency manifests."""
    globs: set[str] = set()
    target_dirs: set[str] = set()
    for raw in task_target_paths:
        target = raw.replace("\\", "/")
        globs.add(target)  # the target itself
        parent = _dir_of(target)
        target_dirs.add(parent)
        if parent:
            globs.add(f"{parent}/**")  # the surrounding directory

    # test directories whose path prefixes intersect a target
    for sig in explore_pass_artifact.test_signatures:
        if _intersects(sig.path, target_dirs):
            globs.add(sig.path)
            sig_dir = _dir_of(sig.path) or sig.path
            globs.add(f"{sig_dir}/**")

    # dependency_bump: the manifest/lockfile paths are in scope by construction
    if task_class == "dependency_bump":
        for manifest in explore_pass_artifact.dependency_manifests:
            globs.add(manifest.path)
            if posixpath.basename(manifest.path).lower() in _MANIFEST_BASENAMES:
                # also allow the sibling lockfile dir
                mdir = _dir_of(manifest.path)
                if mdir:
                    globs.add(f"{mdir}/*.lock")

    return sorted(globs)
