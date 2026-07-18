"""Worktree hygiene: normalize bytecode-cache state before the harness's git surfaces read it.

A worker exercising the code (a refactor's byte-identity check, the ACI test runner, the verifier's
own pytest run) generates ``__pycache__/*.pyc`` and ``.pytest_cache/`` — compiler exhaust, not writes.
Two live failures shaped this module: (rev 0.3.58) in a target repo without a ``.gitignore``, untracked
caches appeared in ``git status``/``git add -A`` and a real refactor task was rejected over them; then
(rev 0.3.59) a repo whose caches were already TRACKED — committed by the harness's own pre-fix scratch
commits — defeated both the gitignore and the v1 rm-tree purge, whose deletions of tracked files were
themselves scope violations.

The contract after ``purge_bytecode_caches``: cache dirs contain exactly the tracked-at-HEAD cache
files and nothing else. Untracked cache trees are deleted; tracked cache paths are restored to HEAD
content (``git checkout HEAD --``, NOT ``checkout --`` — the latter restores from the INDEX, so a
worker that staged a poisoned tracked ``.pyc`` would get it faithfully re-materialized). Nothing under
a cache dir can ever change through the harness: no ``M``/``D``/untracked porcelain noise, nothing
cache-related staged by ``add -A``, and hand-written payload in a tracked cache file is reverted.

A bare ``.pyc`` OUTSIDE a cache dir is a real (suspicious) write — untouched, so scope checks see it.
Symlinked cache dirs are SKIPPED, never followed — a worker could otherwise point ``__pycache__`` at
in-scope files to get them silently deleted pre-check. Non-git roots: the git steps no-op silently
(the rm-tree step alone applies).

Non-Python build output (rev 0.3.98): ``cargo test`` creates ``target/`` exactly as pytest creates
``__pycache__`` — compiler exhaust the worker or verifier generates before the scope check reads
``git status``, which on a repo without a matching ``.gitignore`` would false-trip the out-of-scope
rejection (the same failure class as rev 0.3.58, one language over). ``target`` is purged too, but under
a stricter rule than the bytecode caches: it is deleted **only when UNTRACKED**, and it is **never**
restored-to-HEAD. A directory named ``target`` at any depth that holds TRACKED files (a vendored dir, or
source that happens to be named ``target``) is left entirely alone — otherwise a developer's in-scope
edit under it would silently vanish before the verifier read the diff (reviewer finding). Bytecode caches
keep the delete-all + restore-tracked rule (a ``.pyc`` is never real source). ``node_modules`` is
deliberately NOT purged: unlike ``target`` it holds installed dependencies, so deleting it every task
would break a test run that doesn't reinstall — handled when a JS build is actually driven.
"""

import os
import shutil
import subprocess

_CACHE_DIR_NAMES = ("__pycache__", ".pytest_cache")  # bytecode caches: delete all + restore-tracked-to-HEAD
_BUILD_OUTPUT_NAMES = ("target",)                    # cargo build output: delete only when UNTRACKED

# The .gitignore seeded into a fresh build target (TUI + panel prepare_target import this — a
# rev-0.3.71-class parity pair). node_modules/ is ignored rather than purged (see the docstring:
# deleting installed deps breaks test runs that don't reinstall); target/ likewise belongs here so
# a fresh Rust target never even shows as untracked.
SEEDED_GITIGNORE = "__pycache__/\n*.py[cod]\n.pytest_cache/\nnode_modules/\ntarget/\n"
_CHECKOUT_BATCH = 100  # paths per git call, far under the Windows command-line limit


def _is_cache_path(path: str) -> bool:
    """True if any path segment is a bytecode-cache dir name (repo-relative, forward slashes).

    Used only to select the tracked paths that get restored-to-HEAD — build-output names are excluded
    so a tracked file under a legit ``target`` is never reverted.
    """
    return any(seg in _CACHE_DIR_NAMES for seg in path.split("/"))


def _tracked_paths(root) -> list[str]:
    """Repo-relative tracked paths (forward slashes), or [] outside a git repo. ``-z``: NUL-delimited,
    immune to core.quotepath C-quoting of non-ASCII paths."""
    ls = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True)
    if ls.returncode != 0 or not ls.stdout:
        return []
    return [p for p in ls.stdout.split("\0") if p]


def purge_bytecode_caches(root) -> int:
    """Normalize cache/build-output state under root; return the count of trees removed.

    Step 1 deletes every ``__pycache__``/``.pytest_cache`` tree (any depth) and every UNTRACKED
    ``target`` tree (symlinks skipped, errors ignored — hygiene must never break the run it protects).
    Step 2 restores any TRACKED bytecode-cache paths to HEAD content, so a repo with legacy-committed
    caches produces zero diff noise and a staged/modified tracked cache file cannot ship.
    """
    tracked = _tracked_paths(root)
    root_str = str(root)

    def _has_tracked_under(rel_dir: str) -> bool:
        prefix = rel_dir + "/"
        return any(p == rel_dir or p.startswith(prefix) for p in tracked)

    purged = 0
    for dirpath, dirnames, _ in os.walk(root, followlinks=False):
        for name in list(dirnames):
            is_cache = name in _CACHE_DIR_NAMES
            is_build = name in _BUILD_OUTPUT_NAMES
            if not (is_cache or is_build):
                continue
            target = os.path.join(dirpath, name)
            dirnames.remove(name)  # don't descend into what we're deleting (or deliberately leaving)
            if os.path.islink(target):
                continue  # never follow/delete-through a symlinked dir
            if is_build:
                rel = os.path.relpath(target, root_str).replace("\\", "/")
                if _has_tracked_under(rel):
                    continue  # a tracked 'target' (vendored/source) — leave it, don't revert in-scope edits
            shutil.rmtree(target, ignore_errors=True)
            purged += 1

    # Step 2: restore tracked bytecode-cache paths to HEAD (no-op outside a git repo / with none tracked).
    to_restore = [p for p in tracked if _is_cache_path(p)]
    for i in range(0, len(to_restore), _CHECKOUT_BATCH):
        # :(literal) — checkout pathspecs treat wildcards as active; a hostile upstream filename
        # must not over-match or fail the batch.
        batch = [f":(literal){p}" for p in to_restore[i:i + _CHECKOUT_BATCH]]
        subprocess.run(["git", "-C", str(root), "checkout", "HEAD", "--", *batch],
                       capture_output=True, text=True)
    return purged
