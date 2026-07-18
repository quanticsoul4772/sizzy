"""Promote the operator's chosen work-item candidate to a signed-pending spec (issue-discovery step D).

After `run_discover` surfaces candidates and the operator selects one (`devharness work-items select <id>`),
this drafts a SpecArtifact from the pick (no interview) and persists it signed=0. Then sign it and run the
existing director + developer drivers to build it.

Run:  DEVHARNESS_CORRELATION_ID=<slug> python scripts/run_promote.py
"""

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime"))

from devharness import boot  # noqa: E402
from devharness.cli._bus import projected_bus  # noqa: E402
from devharness.migrate import migrate  # noqa: E402
from devharness.mcp.parallax import ParallaxClient  # noqa: E402
from devharness.roles.promote import promote  # noqa: E402

CORRELATION_ID = os.environ.get("DEVHARNESS_CORRELATION_ID", "discovery")


def _parallax_cfg():
    path = Path.home() / ".claude.json"
    if not path.exists():
        return None
    server = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {}).get("parallax")
    return {"parallax": server} if server else None


def main() -> int:
    # A stray ANTHROPIC_API_KEY kills the SDK subprocess at launch (exit 1); the harness bills
    # through the claude.ai login. Same posture as the console (tui.py) — rev 0.3.57.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    db_path = os.environ.get("DEVHARNESS_DB") or str(REPO / "var" / "devharness.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    migrate(conn)
    boot.run_boot_checks()
    bus = projected_bus(conn)
    cfg = _parallax_cfg()
    parallax = ParallaxClient(mcp_servers=cfg) if cfg else None

    spec_id = asyncio.run(promote(conn, bus, CORRELATION_ID, parallax=parallax))

    # SC-6: promote's parallax spend. Role-scoped — a spec draft has no task yet. Zero emits nothing.
    spent = float(getattr(parallax, "total_cost_usd", 0) or 0) if parallax is not None else 0.0
    if spent > 0:
        bus.emit_sync(
            "cost_spent",
            {"role": "promote", "amount_usd": spent,
             "model": getattr(parallax, "model", "") or "",
             "spent_at_millis": int(time.time() * 1000), "correlation_id": CORRELATION_ID},
            correlation_id=CORRELATION_ID,
        )

    print(f"[run_promote] spec drafted (signed=0): {spec_id}")
    print(f'[run_promote] review + sign:  DEVHARNESS_DB="{db_path}" python -m devharness.cli.sign {spec_id}')
    print(f"[run_promote] then build:  DEVHARNESS_DIRECTOR_DECOMPOSE=1 DEVHARNESS_TARGET_REPO=<repo> "
          f"DEVHARNESS_CORRELATION_ID={CORRELATION_ID} python scripts/run_director.py  (then run_developer.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
