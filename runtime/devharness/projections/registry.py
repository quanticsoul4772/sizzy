"""Projection registry (B0.3).

Empty until later phases register projections. A projection contributes a table
name (cleared on rebuild) and one or more handlers keyed by ``event_type``. No
projections are defined yet — population waits on operator design.
"""

import sqlite3
from collections import defaultdict
from typing import Callable

# A handler applies one event (as a column->value dict) to the projection tables.
Handler = Callable[[sqlite3.Connection, dict], None]


class ProjectionRegistry:
    """Holds the projection tables to rebuild and the per-event_type handlers."""

    def __init__(self) -> None:
        self._tables: list[str] = []
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def register_table(self, table: str) -> None:
        if table not in self._tables:
            self._tables.append(table)

    def register_handler(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def tables(self) -> list[str]:
        return list(self._tables)

    def handlers_for(self, event_type: str) -> list[Handler]:
        return list(self._handlers.get(event_type, ()))
