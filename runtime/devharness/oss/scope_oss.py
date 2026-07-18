"""OSS file-scope tightening (B4.4, §S5).

An OSS contribution's scope_boundary is the B3.1 BUILD-class derivation tightened by two OSS rules:
(1) no escape — every glob must stay inside the upstream worktree (no `..`, no absolute path to
/etc//tmp/harness internals); (2) an optional per-upstream allowlist (DEVHARNESS_OSS_ALLOWED_PATHS,
a JSON map {upstream_repo: [glob, ...]}) which, when set, intersects the derived scope. The B2.1
scope_gate enforces the resulting boundary at admission — B4.4 only tightens the derivation side.
"""

import json
import os
from fnmatch import fnmatch

_HARNESS_PREFIXES = (".git/", ".devharness")


def is_safe_oss_path(glob: str) -> bool:
    """True iff a scope glob stays inside the upstream worktree (no escape)."""
    p = (glob or "").replace("\\", "/")
    if not p:
        return False
    if p.startswith("/"):  # absolute path (incl. /etc, /tmp) escapes the worktree
        return False
    if ".." in p.split("/"):  # parent-dir traversal escapes the worktree
        return False
    normalized = p[2:] if p.startswith("./") else p  # drop a single leading ./ (not the dot in .git)
    if any(normalized.startswith(prefix) for prefix in _HARNESS_PREFIXES) or ".devharness-worktrees" in p:
        return False
    return True


def _allowlist_for(upstream_repo: str) -> list[str]:
    raw = os.environ.get("DEVHARNESS_OSS_ALLOWED_PATHS", "")
    if not raw:
        return []
    try:
        return list(json.loads(raw).get(upstream_repo, []))
    except (json.JSONDecodeError, AttributeError):
        return []


def _within_allowlist(glob: str, allowlist: list[str]) -> bool:
    g = glob.replace("\\", "/")
    for a in allowlist:
        a = a.replace("\\", "/")
        base = a.rstrip("*").rstrip("/")
        if g == a or (base and g.startswith(base + "/")) or fnmatch(g, a):
            return True
    return False


def tighten_oss_scope(globs, upstream_repo: str) -> list[str]:
    """Filter the derived globs to safe-and-allowed paths for an OSS contribution."""
    safe = [g for g in globs if is_safe_oss_path(g)]
    allowlist = _allowlist_for(upstream_repo)
    if allowlist:
        safe = [g for g in safe if _within_allowlist(g, allowlist)]
    return sorted(set(safe))
