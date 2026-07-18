"""Single-writer lock primitive (B2.0, Invariant 1 / commitment 11).

At most one writer holds the lock at a time. Lock state is a *projection* of the
lock events: ``acquire``/``release`` check ``proj_lock`` and emit
``write_lock_acquired`` / ``write_lock_released``; the projection handlers
(``handlers.py``) write the ``proj_lock`` row from those events. This keeps the
event log the source of truth and the lock state rebuildable (Invariant 8). The
``event_bus`` passed in must carry the lock handlers (a registry-equipped bus) so
the row lands before the next acquire's check.
"""

import time
from dataclasses import dataclass
from uuid import uuid4

import msgspec

from devharness.events.registry import WriteLockAcquired, WriteLockReleased


class LockHeldByAnotherRole(RuntimeError):
    """Raised when acquiring a lock that is already held."""


class LockNotHeld(RuntimeError):
    """Raised when releasing a token with no matching lock row."""


@dataclass(frozen=True)
class LockToken:
    lock_token: str
    holder_role: str
    correlation_id: str


def _now(now_millis):
    return (now_millis or (lambda: int(time.time() * 1000)))()


class SingleWriterLock:
    """Exclusive write lock backed by the single ``proj_lock`` row."""

    def acquire(self, holder_role, correlation_id, event_bus, conn, *, now_millis=None) -> LockToken:
        held = conn.execute("SELECT holder_role, correlation_id FROM proj_lock LIMIT 1").fetchone()
        if held is not None:
            raise LockHeldByAnotherRole(
                f"write lock held by {held[0]} for correlation_id {held[1]}"
            )
        token = uuid4().hex
        event_bus.emit_sync(
            "write_lock_acquired",
            msgspec.to_builtins(
                WriteLockAcquired(
                    lock_token=token,
                    holder_role=holder_role,
                    correlation_id=correlation_id,
                    acquired_at_millis=_now(now_millis),
                )
            ),
            correlation_id=correlation_id,
        )
        return LockToken(lock_token=token, holder_role=holder_role, correlation_id=correlation_id)

    def release(self, token: LockToken, event_bus, conn, *, now_millis=None) -> None:
        row = conn.execute("SELECT lock_token FROM proj_lock WHERE lock_token = ?", (token.lock_token,)).fetchone()
        if row is None:
            raise LockNotHeld(f"no held lock for token {token.lock_token}")
        event_bus.emit_sync(
            "write_lock_released",
            msgspec.to_builtins(
                WriteLockReleased(
                    lock_token=token.lock_token,
                    holder_role=token.holder_role,
                    correlation_id=token.correlation_id,
                    released_at_millis=_now(now_millis),
                )
            ),
            correlation_id=token.correlation_id,
        )
