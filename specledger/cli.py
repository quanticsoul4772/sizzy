"""CLI entry point: run the checks and emit the JSON report.

Exit code is 0 only when there are no violations, 1 otherwise. The report is
always written to stdout as JSON.
"""

import argparse
import json
import sys
from pathlib import Path

from specledger.checks import run_all_checks
from specledger.model import SEVERITY_ERROR
from specledger.report import build_report
from specledger.repo import RepoNotFound, find_repo_root


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m specledger",
        description="Read-only repo-consistency checks for the devharness repository.",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Path to start repo discovery from (default: current working directory).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run all checks and print the JSON report. Returns the process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else list(argv))

    start = Path(args.repo_root) if args.repo_root is not None else Path.cwd()
    try:
        repo_root = find_repo_root(start)
    except RepoNotFound as exc:
        report = {
            "ok": False,
            "violations": [
                {"check": "repo_discovery", "severity": SEVERITY_ERROR, "detail": str(exc)}
            ],
        }
        print(json.dumps(report, indent=2))
        return 1

    violations = run_all_checks(repo_root)
    report = build_report(violations)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
