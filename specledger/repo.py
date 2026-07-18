"""Repo discovery: locate the devharness repo root without hardcoded paths."""

from pathlib import Path


class RepoNotFound(Exception):
    """Raised when no devharness repo root can be found from a start directory."""


def find_repo_root(start: Path | str | None = None) -> Path:
    """Walk up from ``start`` to the directory containing both ``.git`` and
    ``devharness-spec.md``.

    ``.git`` may be a directory (normal clone) or a file (git worktree); both
    satisfy the check. The first matching ancestor is returned.

    Raises:
        RepoNotFound: if no such directory exists at or above ``start``.
    """
    base = Path(start) if start is not None else Path.cwd()
    base = base.resolve()
    for candidate in (base, *base.parents):
        if (candidate / ".git").exists() and (candidate / "devharness-spec.md").is_file():
            return candidate
    raise RepoNotFound(
        f"no devharness repo root (a directory containing both .git and "
        f"devharness-spec.md) found at or above {base}"
    )
