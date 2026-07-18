"""``devharness sweep <store>`` — run the live invariant monitor's behavioural checks over an existing
event store's whole log, as a READ-ONLY operator diagnostic (rev 0.3.94).

The same retroactive sweep that surfaced the rev-0.3.93 monitor re-drive blind spots, made repeatable.
Strictly read-only: the store is opened ``mode=ro`` (a stray write is impossible), NEVER migrated, never
created. It emits nothing — persisting findings is ``run_maintenance``'s job (in-process, chain-safe).

Reuses ``monitor.checks.all_violations`` verbatim (all 7 stream-checkable invariants: 1/5/7/9/10/12/17), so
the CLI and the live monitor can never diverge.

Exit codes: 0 = clean, 1 = violations found (NOTE: ``1`` means "violations", unlike ``retro``'s
"refused"), 2 = usage / unreadable / too-old store.
"""

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from devharness.monitor.checks import all_violations


def _open_readonly(resolved: Path) -> sqlite3.Connection:
    """Open the store READ-ONLY. Prefer OS-level ``mode=ro`` (cannot write or create anything); fall back
    to a ``query_only`` connection when ``mode=ro`` can't establish shared memory against a WAL store."""
    try:
        conn = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
        conn.execute("SELECT COUNT(*) FROM sqlite_master")  # force the open so a ro/WAL failure surfaces now
        return conn
    except sqlite3.OperationalError:
        conn = sqlite3.connect(str(resolved))
        conn.execute("PRAGMA query_only = ON")  # writes rejected at the SQLite layer
        return conn


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="devharness sweep",
        description="Run the invariant monitor's checks over a store's whole log (read-only). "
                    "Exit 0=clean, 1=violations found, 2=error.")
    parser.add_argument("store", help="path to the event store (.db) to sweep")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    resolved = Path(args.store).resolve()
    if not resolved.exists():
        sys.stderr.write(f"no event store at {resolved} — sweep does not create one\n")
        return 2
    try:
        conn = _open_readonly(resolved)
        viols = all_violations(conn, include_orphans=True)
    except sqlite3.OperationalError as exc:
        sys.stderr.write(f"cannot sweep {resolved}: {exc} — store schema predates the monitor checks "
                         f"or is not a devharness event store\n")
        return 2

    if not viols:
        sys.stdout.write(f"clean — no invariant violations in {resolved.name}\n")
        return 0

    by_inv = defaultdict(list)
    for v in viols:
        by_inv[v.invariant_number].append(v)
    for inv in sorted(by_inv):
        for v in by_inv[inv]:
            task = f" task={v.task_id}" if v.task_id else ""
            sys.stdout.write(f"  Inv {inv:<2} {v.property}{task}  {v.detail}\n")
    counts = ", ".join(f"Inv {i}: {len(by_inv[i])}" for i in sorted(by_inv))
    sys.stdout.write(f"{len(viols)} violation(s) across {len(by_inv)} invariant(s)  ({counts})\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
