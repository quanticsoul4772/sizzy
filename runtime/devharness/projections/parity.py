"""Projection rebuild and parity check (B0.3, Invariant 8).

``rebuild`` drops all registered projection rows and replays the event log through
the registry. ``check_projection_rebuild_parity`` snapshots the incremental state,
rebuilds from scratch, and asserts row-equality — the Invariant 8 guarantee
(``check_projection_rebuild_parity`` is the name declared in constitution C5's
claim set; the boot-check entry registered in B0.4 must use this exact name).

With an empty registry both are vacuously green; real coverage arrives when
projections land.
"""

import sqlite3

from .registry import ProjectionRegistry


class ParityError(RuntimeError):
    """Raised when a from-scratch rebuild does not match the incremental state."""


def _iter_events(conn: sqlite3.Connection):
    cur = conn.execute(
        "SELECT seq, event_id, correlation_id, event_type, payload, prev_hash, hash "
        "FROM events ORDER BY seq"
    )
    columns = [d[0] for d in cur.description]
    for row in cur:
        yield dict(zip(columns, row))


def _snapshot(conn: sqlite3.Connection, tables: list[str]) -> dict[str, list]:
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in tables}


def rebuild(conn: sqlite3.Connection, registry: ProjectionRegistry) -> None:
    """Drop all projection rows and reconstruct them by replaying the event log."""
    for table in registry.tables():
        conn.execute(f"DELETE FROM {table}")
    for event in _iter_events(conn):
        for handler in registry.handlers_for(event["event_type"]):
            handler(conn, event)
    conn.commit()


def check_projection_rebuild_parity(conn: sqlite3.Connection, registry: ProjectionRegistry) -> bool:
    """Assert incremental projection state equals a from-scratch rebuild (Invariant 8).

    Returns ``True`` when they match; raises ``ParityError`` on divergence. Vacuously
    ``True`` with an empty registry.
    """
    before = _snapshot(conn, registry.tables())
    rebuild(conn, registry)
    after = _snapshot(conn, registry.tables())
    for table in registry.tables():
        if before[table] != after[table]:
            raise ParityError(f"projection {table} diverges from a from-scratch rebuild")
    return True
