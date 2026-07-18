"""specledger — a dependency-free repo-consistency checker for devharness.

Runs four read-only checks against the devharness repo and reports any
violations as JSON. Stdlib only; never mutates the repo.

Checks:
    migration_contiguity        schema/migrations numbering is contiguous from 0001
    event_dispatch_coverage     every EVENT_TYPES entry is in the dashboard dispatch list
    changelog_sha_resolvable    every CHANGELOG closure SHA resolves in git
    orphaned_tiles              dashboard TILE_MANIFEST matches spec §S9
"""

from specledger.model import Violation
from specledger.checks import (
    CHECKS,
    check_changelog_sha_resolvable,
    check_event_dispatch_coverage,
    check_migration_contiguity,
    check_orphaned_tiles,
    run_all_checks,
)
from specledger.report import build_report
from specledger.repo import RepoNotFound, find_repo_root

__all__ = [
    "Violation",
    "CHECKS",
    "check_migration_contiguity",
    "check_event_dispatch_coverage",
    "check_changelog_sha_resolvable",
    "check_orphaned_tiles",
    "run_all_checks",
    "build_report",
    "find_repo_root",
    "RepoNotFound",
]
