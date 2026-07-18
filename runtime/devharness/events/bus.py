"""Event log writer and hash-chain integrity check (B0.2).

``EventBus.emit_sync`` is the sole code path that writes the ``events`` table: it
appends a hash-chained, append-only event and requires a ``correlation_id``
(Invariant 9). ``verify_chain`` recomputes the chain over the whole log and raises
on any break, which is what fails boot (Invariant 7).

Canonical content for the hash (chosen here; documented in the B0.2 commit):
``sha256(prev_hash + RS + event_id + US + correlation_id + US + event_type + US + payload)``
where US = US (0x1f) and RS = RS (0x1e) are ASCII field separators, and ``payload``
is JSON serialized with sorted keys and no insignificant whitespace. The genesis
event chains from an empty prev_hash.
"""

import hashlib
import json
import sqlite3
from uuid import uuid4

GENESIS_PREV = ""
_US = "\x1f"  # unit separator between fields of the canonical content
_RS = "\x1e"  # record separator between prev_hash and the content


class IntegrityError(RuntimeError):
    """Raised when the event log's hash chain does not verify."""


def _hash(prev_hash: str, event_id: str, correlation_id: str, event_type: str, payload: str) -> str:
    content = _US.join((event_id, correlation_id, event_type, payload))
    return hashlib.sha256((prev_hash + _RS + content).encode("utf-8")).hexdigest()


def _canonical_payload(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class EventBus:
    """Sole writer to ``events``. Appends hash-chained events, never updates or deletes.

    When constructed with a ``ProjectionRegistry``, ``emit_sync`` applies that
    event's registered handlers immediately after the append-and-hash step, in the
    same transaction — incremental projection maintenance. A from-scratch replay
    (``rebuild``) over the same log must reproduce this incremental state
    (Invariant 8), which the parity check verifies.
    """

    def __init__(self, conn: sqlite3.Connection, registry=None):
        self._conn = conn
        self._registry = registry

    def emit_sync(self, event_type: str, payload, correlation_id: str) -> tuple[str, str]:
        """Append one event, apply its handlers, commit; return ``(event_id, hash)``.

        Raises ``ValueError`` if ``correlation_id`` is missing (Invariant 9).
        """
        if not correlation_id:
            raise ValueError("correlation_id is required")
        event_id = uuid4().hex
        body = _canonical_payload(payload)
        # Atomic append (Inv 7): take the sqlite write lock BEFORE reading the tail hash and hold it through
        # the INSERT, so a concurrent writer (a second process/thread on this store — e.g. `devharness sign`
        # while the console holds the file) can't read the same prev_hash and fork the chain. BEGIN IMMEDIATE
        # acquires the write lock up front; a contender blocks on busy_timeout then reads the NEW tail.
        #
        # Begin only when no transaction is already open. A caller that did a related direct-DML WRITE first
        # (e.g. inserting the artifact row, then emitting the event as one batch — the artifacts path) is
        # already inside a transaction that holds the write lock, so its tail-read is already race-free and a
        # manual BEGIN here would raise "cannot start a transaction within a transaction". The unconditional
        # commit below still commits that whole batch, preserving the existing "handlers + the caller's DML
        # commit together" contract (Inv-8 parity). The explicit rollback is load-bearing: the connection is
        # shared, so a mid-emit failure (a projection handler raising) must undo the batch AND clear the
        # transaction, or the next emit_sync inherits a poisoned open transaction.
        own_txn = not self._conn.in_transaction
        if own_txn:
            self._conn.execute("BEGIN IMMEDIATE")
        try:
            prev_hash = self._last_hash()
            digest = _hash(prev_hash, event_id, correlation_id, event_type, body)
            cursor = self._conn.execute(
                "INSERT INTO events (event_id, correlation_id, event_type, payload, prev_hash, hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, correlation_id, event_type, body, prev_hash, digest),
            )
            if self._registry is not None:
                event = {
                    "seq": cursor.lastrowid,
                    "event_id": event_id,
                    "correlation_id": correlation_id,
                    "event_type": event_type,
                    "payload": body,
                    "prev_hash": prev_hash,
                    "hash": digest,
                }
                for handler in self._registry.handlers_for(event_type):
                    handler(self._conn, event)
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        return event_id, digest

    def _last_hash(self) -> str:
        row = self._conn.execute(
            "SELECT hash FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return row[0] if row is not None else GENESIS_PREV


def verify_chain(conn: sqlite3.Connection) -> int:
    """Recompute the chain over all events in ``seq`` order; return the count verified.

    Raises ``IntegrityError`` at the first row whose ``prev_hash`` or ``hash`` does not
    match recomputation — the break that fails boot (Invariant 7).
    """
    prev_hash = GENESIS_PREV
    count = 0
    for seq, event_id, correlation_id, event_type, payload, stored_prev, stored_hash in conn.execute(
        "SELECT seq, event_id, correlation_id, event_type, payload, prev_hash, hash "
        "FROM events ORDER BY seq"
    ):
        if stored_prev != prev_hash:
            raise IntegrityError(f"event seq {seq}: prev_hash does not link to the prior event")
        expected = _hash(prev_hash, event_id, correlation_id, event_type, payload)
        if stored_hash != expected:
            raise IntegrityError(f"event seq {seq}: hash does not match recomputation")
        prev_hash = stored_hash
        count += 1
    return count
