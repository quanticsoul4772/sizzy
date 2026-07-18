"""`devharness prune` — operator-authorized removal of EXPIRED trust grants (the §S6 delete path).

The maintenance PruneCycle only REPORTS expired trust grants (cycles never delete data). This is the
separate authorized companion that actually removes them — emitting one trust_grant_pruned event per
grant. Defaults to a dry-run (lists what would be pruned); ``--confirm --reason TEXT`` actually prunes.
The authorizer is DEVHARNESS_OPERATOR_ID (else the OS user).
"""

import argparse
import getpass
import os
import sys
import time
from pathlib import Path

from devharness.cli._bus import open_store, projected_bus
from devharness.maintenance.prune import expired_trust_grants, prune_expired_trust_grants


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="devharness prune")
    parser.add_argument("--confirm", action="store_true", help="actually prune (default: dry-run list)")
    parser.add_argument("--reason", default="", help="required with --confirm: why these grants are pruned")
    args = parser.parse_args(argv)
    if not Path(db).exists():
        print(f"devharness prune: no event DB at {db}", file=sys.stderr)
        return 1
    conn = open_store()
    at = int(time.time() * 1000)
    expired = expired_trust_grants(conn, at_millis=at)
    if not expired:
        print("devharness prune: no expired trust grants to prune.")
        return 0
    print(f"devharness prune: {len(expired)} expired trust grant(s):")
    for grant_row_id, role_name, task_class, granted_at in expired:
        print(f"  - #{grant_row_id} {role_name}/{task_class} granted @ {granted_at}")
    if not args.confirm:
        print("\n(dry-run — pass --confirm --reason TEXT to actually prune)")
        return 0
    if not args.reason:
        print("devharness prune: --confirm requires --reason TEXT", file=sys.stderr)
        return 2
    authorized_by = os.environ.get("DEVHARNESS_OPERATOR_ID") or getpass.getuser()
    n = prune_expired_trust_grants(conn, projected_bus(conn), authorized_by, args.reason, now_millis=lambda: at)
    conn.commit()
    print(f"\npruned {n} expired trust grant(s) (authorized by {authorized_by}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
