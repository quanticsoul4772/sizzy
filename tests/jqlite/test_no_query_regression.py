"""Regression: `python -m jqlite` with no query argument is a usage error and must exit 2.

The spec's interfaces state: "Positional argument: a single query string … absence … of the query
exits 2." Before the fix, jqlite defaulted a missing query to identity and exited 0. This test
fails at that baseline (demonstrating the bug) and passes once no-query exits 2 (EXIT_USAGE).
"""

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_query_argument_exits_usage_2():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite"],
        input='{"a": 1}',
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 2, (
        f"`jqlite` with no query argument must exit 2 (usage error), got {proc.returncode}"
    )
