"""Drive the live DiscoveryRole: read-only analysis of a repo that surfaces candidate work items.

Reads DEVHARNESS_TARGET_REPO's code via a read-only Agent SDK session (Read/Grep/Glob only, no writes) and
emits work_item_candidate events into proj_work_item_queue. Then the operator picks one — present them with
`python -m devharness.cli.work_items` and the harness records the pick via `devharness answer`.

The SDK worker needs the logged-in auth, not a raw key — run with ANTHROPIC_API_KEY unset.

Run:  DEVHARNESS_TARGET_REPO=<repo> DEVHARNESS_CORRELATION_ID=<slug> python scripts/run_discover.py
"""

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime"))

# The repo discovery analyzes. Defaults to devharness itself; DEVHARNESS_TARGET_REPO points it at any repo.
TARGET = Path(os.environ.get("DEVHARNESS_TARGET_REPO") or REPO)

from devharness import boot  # noqa: E402
from devharness.cli._bus import projected_bus  # noqa: E402
from devharness.migrate import migrate  # noqa: E402
from devharness.roles.discovery import DiscoveryRole  # noqa: E402

CORRELATION_ID = os.environ.get("DEVHARNESS_CORRELATION_ID", "discovery")


def main() -> int:
    # A stray ANTHROPIC_API_KEY kills the SDK subprocess at launch (exit 1); the harness bills
    # through the claude.ai login. Same posture as the console (tui.py) — rev 0.3.57.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    db_path = os.environ.get("DEVHARNESS_DB") or str(REPO / "var" / "devharness.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    migrate(conn)
    boot.run_boot_checks()  # #C4: fail closed at boot before any work
    bus = projected_bus(conn)

    from devharness.models import model_for_tier
    role = DiscoveryRole(
        event_bus=bus, conn=conn, target_repo=str(TARGET), correlation_id=CORRELATION_ID,
        model=model_for_tier("T1"),  # discovery is advisory read-only (rev 0.3.82)
        max_candidates=int(os.environ.get("DEVHARNESS_MAX_CANDIDATES", "6")),
    )
    print(f"[run_discover] db          = {db_path}")
    print(f"[run_discover] target      = {TARGET}")
    print(f"[run_discover] correlation = {CORRELATION_ID}")
    print("[run_discover] analyzing the repo (read-only SDK session)…")

    ids = asyncio.run(role.run())

    print(f"\n[run_discover] surfaced {len(ids)} candidate(s): {ids}")
    print(f"[run_discover] spend: ${role.total_cost_usd:.4f}")
    print(f'[run_discover] present them with:  DEVHARNESS_DB="{db_path}" python -m devharness.cli.work_items')
    return 0 if ids else 1


if __name__ == "__main__":
    raise SystemExit(main())
