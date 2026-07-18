"""Shared helper: build an EventBus that maintains projections incrementally.

Operator CLIs are short-lived event writers. Like the runtime roles and the
research driver, they must emit through a registry-equipped EventBus so the
projections stay consistent with the event log (Invariant 8). A bare
``EventBus(conn)`` appends the event but skips projection maintenance, drifting
the live projections from a from-scratch rebuild (parity then fails).
"""

import os
import sqlite3
import sys
from pathlib import Path

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry

_DEFAULT_DB = str(Path(__file__).resolve().parents[3] / "var" / "devharness.db")


def projected_bus(conn) -> EventBus:
    """An EventBus wired with every projection handler (incremental maintenance)."""
    registry = ProjectionRegistry()
    register_handlers(registry)
    return EventBus(conn, registry=registry)


def open_store() -> sqlite3.Connection:
    """Open + migrate the operator's event store with the console's rev-0.3.63 path hygiene, shared by
    every ``devharness`` CLI (rev 0.3.80).

    A file-backed ``DEVHARNESS_DB`` is resolved to ABSOLUTE before opening — sqlite names no path in
    its errors, and a relative/typo'd value against the wrong cwd otherwise either fails bare or,
    worse, silently CREATES a fresh empty store that ``migrate`` makes look legitimate (an operator
    ``sign``/``answer`` would land in a phantom store — the CLI sibling of the wrong-target
    contamination). A missing parent directory fails closed with the resolved path named; creating a
    new store FILE is allowed (``memory import`` may target one) but ANNOUNCED on stderr, never silent.
    """
    db = os.environ.get("DEVHARNESS_DB") or _DEFAULT_DB
    created = False
    if db != ":memory:":
        resolved = Path(db).resolve()
        if not resolved.parent.is_dir():
            raise SystemExit(
                f"event-store directory does not exist: {resolved.parent} "
                f"(DEVHARNESS_DB resolved to {resolved}) — set DEVHARNESS_DB to an absolute path"
            )
        # rev 0.4.13 content gate (parity with the panel/console): migrate() below would write
        # devharness schema into an existing foreign sqlite file. SystemExit matches this
        # module's existing failure shape.
        if resolved.exists():
            from devharness.migrate import is_event_store

            verdict = is_event_store(resolved)
            if verdict is False:
                raise SystemExit(
                    f"{resolved} exists but is not a devharness event store — refusing to "
                    "migrate a foreign database (delete or rename the file if it should be a "
                    "new store)")
            if verdict is None:
                raise SystemExit(
                    f"{resolved} exists but is unreadable right now — refusing to open a store "
                    "that cannot even be probed (locked by another process?)")
        created = not resolved.exists()
        db = str(resolved)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    migrate(conn)
    if created:
        sys.stderr.write(f"⚠ created NEW EMPTY event store at {db}\n")
    return conn
