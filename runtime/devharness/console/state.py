"""Read-only loop-state reader for the operator console.

``read_loop_state`` derives the console's display from the event-sourced
projections with SELECT-only queries. The console never writes the event store
or a projection directly — display is derived purely by reading the projections
the runtime maintains. State-changing operator actions, when added, route
exclusively through ``EventBus.emit_sync`` (the ``cli/_bus`` ``projected_bus``
writer), never through this module.
"""

import sqlite3
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LoopState:
    """A read-only snapshot of where the loop stands, derived from projections."""

    active_role: str | None
    role_event_seq: int | None
    signed_spec_id: str | None
    signed_by: str | None
    tasks_by_state: dict[str, int] = field(default_factory=dict)
    event_count: int = 0

    @property
    def spec_signed(self) -> bool:
        return self.signed_spec_id is not None


def read_loop_state(conn: sqlite3.Connection) -> LoopState:
    """Read the current loop state from the projections (SELECT-only, no writes)."""
    role_row = conn.execute(
        "SELECT role, event_seq FROM proj_role_state WHERE id = 1"
    ).fetchone()
    active_role = role_row[0] if role_row is not None else None
    role_event_seq = role_row[1] if role_row is not None else None

    spec_row = conn.execute(
        "SELECT spec_id, signed_by FROM proj_signed_spec "
        "ORDER BY signed_at_millis DESC LIMIT 1"
    ).fetchone()
    signed_spec_id = spec_row[0] if spec_row is not None else None
    signed_by = spec_row[1] if spec_row is not None else None

    tasks_by_state: dict[str, int] = {}
    for state, count in conn.execute(
        "SELECT current_state, COUNT(*) FROM proj_task_lifecycle GROUP BY current_state"
    ):
        tasks_by_state[state] = count

    (event_count,) = conn.execute("SELECT COUNT(*) FROM events").fetchone()

    return LoopState(
        active_role=active_role,
        role_event_seq=role_event_seq,
        signed_spec_id=signed_spec_id,
        signed_by=signed_by,
        tasks_by_state=tasks_by_state,
        event_count=event_count,
    )
