"""The panel's single event-writer (single-writer invariant, web edition).

The panel is the sole process writing the event store, exactly as the console is. But an HTTP server
handles requests on many threads, so — unlike the console, which funnels every worker emit back to one
UI thread via ``call_from_thread`` (``console/tui.py`` ``_ProxyBus``) — the panel serializes every
``emit_sync`` through ONE connection under ONE re-entrant lock.

``EventBus.emit_sync`` is a non-atomic read-then-insert on the event hash chain (``events/bus.py``);
two connections, or two threads on one connection, emitting concurrently would fork/corrupt the chain.
One writer connection, one lock:

- **Build workers** (``panel.worker``) read on their OWN connection and pass this object as their
  ``bus``; each ``emit_sync`` briefly takes the lock. They never hold it across the minutes-long step.
- **Inline actions** (sign/reject/integrate/…) take the lock for the WHOLE action and use
  ``writer.conn`` for their reads+writes — the web analog of the TUI running inline actions on its one
  main connection. The lock is re-entrant so the action's own ``emit_sync`` re-acquires on the same
  thread without deadlock.
- **State reads** (``/state``) never touch this connection; they open their own read connection (WAL
  makes concurrent reads safe alongside the single writer).
"""

import sqlite3
import threading

from devharness.cli._bus import projected_bus
from devharness.migrate import migrate


class PanelWriter:
    """The one event-writer for a panel session: a shared write connection + a re-entrant lock."""

    def __init__(self, db_path: str) -> None:
        # check_same_thread=False: the write connection is shared across HTTP-handler / build-worker
        # threads, but EVERY use is serialized by _lock, so it is single-threaded-at-a-time in fact.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        migrate(self._conn)
        self._bus = projected_bus(self._conn)
        # Re-entrant: an inline action holds the lock for its whole body AND calls emit_sync (which
        # re-takes it on the same thread). A plain Lock would deadlock there.
        self._lock = threading.RLock()

    @property
    def lock(self) -> "threading.RLock":
        """Hold this for the whole of an inline action so its reads+writes on ``conn`` are serialized."""
        return self._lock

    @property
    def conn(self) -> sqlite3.Connection:
        """The write connection — only touch it while holding ``lock``."""
        return self._conn

    def emit_sync(self, *args, **kwargs):
        """Serialized single-writer emit; safe from any thread (build workers pass this as their bus)."""
        with self._lock:
            return self._bus.emit_sync(*args, **kwargs)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
