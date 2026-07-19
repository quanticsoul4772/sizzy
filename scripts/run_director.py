"""Drive the live DirectorRole to plan the signed specledger spec (plan_drafted).

Reads the most recent operator-signed spec for the correlation_id, runs the real
DirectorRole (mcp-reasoning + parallax, zero write tools, no dispatch authority),
and persists a PlanArtifact. The director refuses to plan an unsigned spec.

NOTE on the task decomposition: this DirectorRole does not synthesize tasks from
the spec — run() takes an explicit `tasks=` list or falls back to one generic
`feature` task. So we supply the decomposition the director's reasoning would
otherwise produce: a single new_project_scaffold task (specledger is greenfield),
scoped to its own package + tests. Emit through a registry-equipped EventBus so
plan_drafted / director_decision maintain projections (Invariant 8).

The mcp-reasoning server launch spec is read live at runtime (DEVHARNESS_MCP_CONFIG, else ~/.claude.json).

Run:  python scripts/run_director.py  (a stray ANTHROPIC_API_KEY is cleared at startup)
"""

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime"))

# Telemetry/worktree target — devharness itself by default; an external target sets DEVHARNESS_TARGET_REPO.
TARGET = Path(os.environ.get("DEVHARNESS_TARGET_REPO") or REPO)

from devharness import boot  # noqa: E402
from devharness.mcp.config import MCPConfigError, server_cfg  # noqa: E402
from devharness.cli._bus import projected_bus  # noqa: E402
from devharness.mcp.mcp_reasoning import MCPReasoningClient  # noqa: E402
from devharness.migrate import migrate  # noqa: E402
from devharness.roles.director import DirectorRole  # noqa: E402

CORRELATION_ID = os.environ.get("DEVHARNESS_CORRELATION_ID", "specledger")

TASKS = [
    {
        "task_class": "new_project_scaffold",
        "description": (
            "Scaffold the specledger package: a stdlib-only CLI (python -m specledger) "
            "running four repo-consistency checks (migration_contiguity, "
            "event_dispatch_coverage, changelog_sha_resolvable, orphaned_tiles), emitting "
            "JSON {ok, violations:[{check,severity,detail}]} to stdout and exiting non-zero "
            "on any violation; fully unit-tested; read-only (never mutates the repo)."
        ),
        "scope_boundary": ["specledger/**", "tests/specledger/**"],
        "dependencies": [],
    }
]


def _server_config(name: str) -> dict:
    """A named MCP server's live launch spec, wrapped (rev 0.4.25: via the single config
    source, honoring DEVHARNESS_MCP_CONFIG with the ~/.claude.json fallback)."""
    try:
        return {name: server_cfg(name)}
    except MCPConfigError as exc:
        sys.exit(str(exc))


def main() -> int:
    # A stray ANTHROPIC_API_KEY kills the SDK subprocess at launch (exit 1); the harness bills
    # through the claude.ai login. Same posture as the console (tui.py) — rev 0.3.57.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    db_path = os.environ.get("DEVHARNESS_DB") or str(REPO / "var" / "devharness.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    migrate(conn)
    boot.run_boot_checks()  # #C4: fail closed at boot before any work

    row = conn.execute(
        "SELECT artifact_id FROM artifacts "
        "WHERE artifact_type = 'spec' AND correlation_id = ? AND signed = 1 "
        "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1",
        (CORRELATION_ID,),
    ).fetchone()
    if row is None:
        sys.exit(f"no signed spec for correlation_id {CORRELATION_ID!r} — run + sign research first")
    spec_id = row[0]

    bus = projected_bus(conn)

    from devharness.health import emit_snapshot, leak_warning  # resource telemetry (every driver, not just developer)
    snap = emit_snapshot(bus, CORRELATION_ID, base_path=str(TARGET))
    print(f"[run_director] resources: {snap['process_count']} procs · {snap['git_process_count']} git · "
          f"{snap['worktree_count']} worktrees · {snap['free_memory_mb']}MB free")
    if (warn := leak_warning(snap)):
        print(f"[run_director] ⚠ {warn}")

    reasoning = MCPReasoningClient(mcp_servers=_server_config("mcp-reasoning"))
    director = DirectorRole.spawn(
        conn=conn, correlation_id=CORRELATION_ID, reasoning=reasoning, event_bus=bus
    )

    print(f"[run_director] db       = {db_path}")
    print(f"[run_director] spec     = {spec_id} (signed)")
    # DEVHARNESS_DIRECTOR_DECOMPOSE=1 -> let the director decompose the spec via mcp-reasoning (#2b);
    # otherwise use the injected TASKS (the pre-#2b workaround, kept for reproducibility).
    decompose = bool(os.environ.get("DEVHARNESS_DIRECTOR_DECOMPOSE"))
    # The injected TASKS are specledger-specific (scope_boundary specledger/**). Planting them into any other
    # project — especially an external target — makes every realized path out-of-scope at the developer, so the
    # build rewinds+rejects every run. They apply ONLY to the specledger correlation; any other project MUST
    # decompose its own signed spec.
    if not decompose and CORRELATION_ID != "specledger":
        sys.exit(f"correlation {CORRELATION_ID!r} has no injected tasks (those are specledger-only); "
                 "set DEVHARNESS_DIRECTOR_DECOMPOSE=1 to decompose the signed spec via mcp-reasoning")
    tasks = None if decompose else TASKS
    print(f"[run_director] planning via {'mcp-reasoning decomposition (#2b)' if decompose else f'{len(TASKS)} injected task(s)'}…")

    plan_id = asyncio.run(director.run(spec_id, CORRELATION_ID, tasks=tasks))

    if plan_id is None:
        print("[run_director] director refused to plan (spec unsigned or intake required)")
        return 1
    print(f"\n[run_director] plan drafted : {plan_id}")
    print(f"[run_director] reasoning spend: ${reasoning.total_cost_usd:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
