"""B5.0: OQ-B5-1 resolution A — the retro fires on EVERY terminal kind (completed + rejected + aborted).

If a future OQ-B5-1=B narrowing scoped the queue to rejected/aborted only, this test would fail —
it is the guard that the every-terminal scope holds.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.scheduler import RetroScheduler


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _terminal(bus, task_id, outcome):
    bus.emit_sync("terminal_outcome", {"task_id": task_id, "outcome": outcome, "detail": "",
                  "correlation_id": "c", "terminated_at_millis": 1}, correlation_id="c")


def test_all_three_terminal_kinds_processed():
    conn, bus = _setup()
    _terminal(bus, "c-done", "completed")
    _terminal(bus, "c-rej", "rejected")
    _terminal(bus, "c-abr", "aborted")
    sched = RetroScheduler()
    processed = []
    while True:
        t = sched.step(conn, bus, now_millis=lambda: 5)
        if t is None:
            break
        processed.append(t)
    # every kind got a retro_run (OQ-B5-1=A, not the rejected/aborted subset)
    assert set(processed) == {"c-done", "c-rej", "c-abr"}
    kinds = {r[0] for r in conn.execute("SELECT terminal_kind FROM proj_retro_runs")}
    assert kinds == {"completed", "rejected", "aborted"}
    # the success-path terminal (completed) is included — the coverage A was chosen for
    assert conn.execute("SELECT count(*) FROM proj_retro_runs WHERE terminal_kind='completed'").fetchone()[0] == 1
