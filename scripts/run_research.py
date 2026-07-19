"""Drive the live ResearchRole front-end for one project (the harness's real first step).

This spawns the actual read-only ResearchRole (parallax + mcp-reasoning, zero write
tools) against a one-line operator seed, runs the operator interview, and lets the
role draft and persist a SpecArtifact. It takes NO write lock and does NOT author the
spec by hand — the role produces it from the interview. That is the whole point: the
spec is earned through the loop, not asserted.

The interview BLOCKS waiting for operator answers. While this runs, answer each
question from the repo root in a SECOND terminal (same DEVHARNESS_DB):

    python -m devharness.cli.answer <question_id>  "<answer text>"

When it prints a spec_id, review the drafted spec, then sign the operator gate:

    python -m devharness.cli.sign <spec_id>

The parallax MCP server launch spec (which carries API keys in its env) is read live
at runtime (DEVHARNESS_MCP_CONFIG, else ~/.claude.json) and passed in memory to the Agent SDK — never embedded
in this file.

Run:  python scripts/run_research.py
"""

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime"))

from devharness import boot  # noqa: E402
from devharness.mcp.config import MCPConfigError, server_cfg  # noqa: E402
from devharness.events.bus import EventBus  # noqa: E402
from devharness.mcp.parallax import ParallaxClient  # noqa: E402
from devharness.models import model_for_tier  # noqa: E402
from devharness.migrate import migrate  # noqa: E402
from devharness.projections.handlers import register_handlers  # noqa: E402
from devharness.projections.registry import ProjectionRegistry  # noqa: E402
from devharness.roles.research import ResearchRole  # noqa: E402

CORRELATION_ID = os.environ.get("DEVHARNESS_CORRELATION_ID", "specledger")

# Gap C: the target repo research grounds the spec in. Default devharness itself; DEVHARNESS_TARGET_REPO
# points it at an external repo, where research runs a read-only explore pass and proposes a fitting feature.
TARGET = Path(os.environ.get("DEVHARNESS_TARGET_REPO") or REPO)
_EXTERNAL = TARGET.resolve() != REPO.resolve()

SEED = os.environ.get("DEVHARNESS_SEED") or (
    # external target: let research propose a feature grounded in the repo's structure (Gap C)
    "Propose and specify one valuable, well-scoped new feature for this existing repository, grounded in "
    "its actual structure; the feature must fit the codebase's language, layout, and test setup, and add "
    "real behaviour the project does not already have."
    if _EXTERNAL else
    # devharness-self default (greenfield specledger seed)
    "A dependency-free Python CLI that checks devharness's own repo for internal "
    "consistency — contiguous migration numbering, every EVENT_TYPES entry present "
    "in the derived dashboard dispatch list, every CHANGELOG closure SHA resolvable "
    "in git, and no orphaned dashboard tiles — exiting non-zero with a structured "
    "report on any violation."
)


def _parallax_server_config() -> dict:
    """The live parallax stdio launch spec (rev 0.4.25: via the single config source,
    honoring DEVHARNESS_MCP_CONFIG with the ~/.claude.json fallback; never embedded)."""
    try:
        return {"parallax": server_cfg("parallax")}
    except MCPConfigError as exc:
        sys.exit(str(exc))


def main() -> int:
    # A stray ANTHROPIC_API_KEY kills the SDK subprocess at launch (exit 1); the harness bills
    # through the claude.ai login. Same posture as the console (tui.py) — rev 0.3.57.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    db_path = os.environ.get("DEVHARNESS_DB") or str(REPO / "var" / "devharness.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")      # let the answer/sign CLIs share the file
    conn.execute("PRAGMA busy_timeout=30000")
    migrate(conn)
    boot.run_boot_checks()  # #C4: fail closed at boot before any work

    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry=registry)

    from devharness.health import emit_snapshot, leak_warning  # resource telemetry (every driver, not just developer)
    snap = emit_snapshot(bus, CORRELATION_ID, base_path=str(TARGET))
    print(f"[run_research] resources: {snap['process_count']} procs · {snap['git_process_count']} git · "
          f"{snap['worktree_count']} worktrees · {snap['free_memory_mb']}MB free")
    if (warn := leak_warning(snap)):
        print(f"[run_research] ⚠ {warn}")

    parallax = ParallaxClient(mcp_servers=_parallax_server_config(), model=model_for_tier("T1"))  # research is advisory (rev 0.3.82)

    role = ResearchRole.spawn(
        conn=conn,
        correlation_id=CORRELATION_ID,
        parallax=parallax,
        event_bus=bus,
        target_repo=str(TARGET) if _EXTERNAL else None,  # Gap C: ground the spec in an external repo's structure
        poll_interval=2.0,
        # Per-question answer window. Default ~30 min; DEVHARNESS_ANSWER_POLL_LIMIT raises it so a slow
        # operator/steering deliberation can't time the interview out and crash the whole research run.
        poll_limit=int(os.environ.get("DEVHARNESS_ANSWER_POLL_LIMIT", "900")),
    )

    print(f"[run_research] db          = {db_path}")
    print(f"[run_research] correlation = {CORRELATION_ID}")
    print("[run_research] interview starting — answer each question from the repo root with:")
    print(f'    DEVHARNESS_DB="{db_path}" python -m devharness.cli.answer <question_id> "<answer>"')
    print(f"    (question ids look like {CORRELATION_ID}-q0, {CORRELATION_ID}-q1, …)\n")

    spec_id = asyncio.run(role.run(SEED, CORRELATION_ID))

    print(f"\n[run_research] spec drafted  : {spec_id}")
    print(f"[run_research] parallax spend: ${parallax.total_cost_usd:.4f}")
    print("[run_research] review the drafted spec, then sign the operator gate:")
    print(f'    DEVHARNESS_DB="{db_path}" python -m devharness.cli.sign {spec_id}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
