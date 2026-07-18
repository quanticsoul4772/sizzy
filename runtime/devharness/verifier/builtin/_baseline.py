"""Shared baseline-reaching for the refactor + bugfix verifiers.

Both verifiers compare a POST-change capture against the PRE-change baseline. The baseline is the B2.4
checkpoint commit (the state before the developer's task change). Reaching it must be robust to whether the
change is UNCOMMITTED (the in-lock acceptance run — `git stash` removes it and HEAD already == checkpoint)
or COMMITTED (the §S5 OSS flow makes the bot-identity commit BEFORE the reviewer re-runs the verifier, so
the tree is clean and `git stash` is a no-op — the captured "baseline" would wrongly equal post). Reaching
the baseline only via `git stash` therefore made the OSS reviewer re-run vacuous: a behaviour-changing
refactor certified "preserved" (baseline == post → no diff) and a fixed bugfix's `baseline_should_fail`
axis saw the already-fixed tree and rejected. The fix reaches the baseline from the checkpoint commit the
verifiers already hold (and previously used only for evidence): stash any uncommitted work, detach-checkout
the checkpoint, capture there, then restore HEAD and the stash.
"""

import os
import subprocess

from devharness.worktree.hygiene import purge_bytecode_caches


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True).stdout.strip()


def _tracked_at_head(cwd, path) -> bool:
    return subprocess.run(["git", "-C", cwd, "cat-file", "-e", f"HEAD:{path}"],
                          capture_output=True).returncode == 0


def at_baseline(cwd, checkpoint_sha, capture_fn, *, overlay=None):
    """Run ``capture_fn()`` at the pre-change baseline (the checkpoint commit) and return its result.

    Robust to a COMMITTED or UNCOMMITTED change. When ``checkpoint_sha`` is falsy or already == HEAD — the
    uncommitted-change case, where stashing alone reaches the baseline — no checkout happens, so the path is
    identical to the prior stash-only behaviour (a no-op change for the non-OSS acceptance run). The HEAD
    detach and the stash are always restored (``finally``).

    ``overlay`` (rev 0.3.73, bugfix-only — refactor passes None, so its path is byte-identical) is a
    ``{repo_relative_path: post_change_content}`` mapping written onto the baseline BEFORE ``capture_fn``
    and cleaned up after. It exists because a `bugfix`'s regression test is NEW/MODIFIED in this task, so
    the ``--include-untracked`` stash removes it — at baseline the test would be ABSENT and
    ``pytest <path>`` would exit "file not found", which the ``baseline_should_fail`` axis would misread as
    "bug demonstrated" (a silent false-certification). Overlaying the test (fix absent) makes the axis real:
    the test present against unfixed code genuinely fails."""
    head = _git(cwd, "rev-parse", "HEAD")
    dirty = bool(_git(cwd, "status", "--porcelain"))
    if dirty:
        _git(cwd, "stash", "push", "--include-untracked", "-m", "devharness-baseline")
    move = bool(checkpoint_sha) and checkpoint_sha != head
    overlaid = dict(overlay or {})
    try:
        if move:
            _git(cwd, "checkout", "--detach", checkpoint_sha)
        for path, content in overlaid.items():
            abspath = os.path.join(cwd, path)
            os.makedirs(os.path.dirname(abspath) or cwd, exist_ok=True)
            with open(abspath, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        return capture_fn()
    finally:
        # restore each overlaid path to its baseline state so the stash pop is clean: a file tracked at
        # HEAD reverts to HEAD content, a purely-new file is removed.
        for path in overlaid:
            if _tracked_at_head(cwd, path):
                _git(cwd, "checkout", "HEAD", "--", path)
            else:
                try:
                    os.remove(os.path.join(cwd, path))
                except OSError:
                    pass
        if move:
            _git(cwd, "checkout", "--detach", head)
        if dirty:
            # the baseline capture ran the suite (pytest), regenerating __pycache__/*.pyc; if those
            # same caches are in the stash's untracked set, `stash pop` aborts ("already exists, no
            # checkout"). Caches are compiler exhaust — purge the working-tree copies so the pop
            # restores cleanly (rev 0.3.73; the rev-0.3.58 cache hazard at a new git surface).
            purge_bytecode_caches(cwd)
            _git(cwd, "stash", "pop")
