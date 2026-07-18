"""Thin, injectable wrapper around the git CLI for read-only SHA resolution.

The default runner shells out to ``git``; tests inject a fake runner so the
checks are exercised without a real repository.
"""

import subprocess
from pathlib import Path
from typing import Callable

# A git runner takes (repo_root, args) and returns a CompletedProcess.
GitRunner = Callable[[Path, list[str]], "subprocess.CompletedProcess"]


def real_git_runner(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    """Run ``git -C <repo_root> <args...>`` read-only, capturing output.

    Raises FileNotFoundError if git is not installed; callers handle that as
    "not a git repository".
    """
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def is_git_repo(repo_root: Path, runner: GitRunner = real_git_runner) -> bool:
    """True iff ``repo_root`` is inside a git work tree."""
    try:
        result = runner(repo_root, ["rev-parse", "--is-inside-work-tree"])
    except FileNotFoundError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def sha_resolvable(repo_root: Path, sha: str, runner: GitRunner = real_git_runner) -> bool:
    """True iff ``sha`` resolves to a commit object via ``git rev-parse``."""
    try:
        result = runner(repo_root, ["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"])
    except FileNotFoundError:
        return False
    return result.returncode == 0
