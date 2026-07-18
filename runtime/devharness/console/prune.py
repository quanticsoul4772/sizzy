"""Operator console prune action — authorize removal of EXPIRED trust grants (the §S6 delete path).

The maintenance PruneCycle only REPORTS expired trust grants (cycles never delete data, the §S6
invariant); the separate operator-authorized companion actually removes them. The ``devharness prune``
CLI is the agent-less driver for that authorized delete; this surface is the SAME operation pressed from
the operator console, with a human in the seat and no LLM agent making the call:

* ``list_expired`` surfaces the expired, non-revoked trust grants an authorized prune would remove
  (SELECT-only — the same set the dry-run CLI lists and the advisory PruneCycle counts).
* ``prune`` issues the canonical ``maintenance.prune.prune_expired_trust_grants`` operation, recording
  one operator-attributed ``trust_grant_pruned`` event per expired grant (the event-sourced delete — the
  handler removes the projection row, reproducible on replay, Inv 8). It REQUIRES a ``reason`` — the
  operator authorization — and refuses a blank one (``EmptyPruneReason``); the operator identity is the
  ``pruned_by`` authorizer. Only EXPIRED, non-revoked grants are ever touched (already invalid at
  point-of-use, so this is storage tidiness, never a correctness/security change).

The prune is recorded through ``EventBus.emit_sync`` — the console's sole sanctioned write path (the
canonical operation emits through the supplied bus); the console issues no event-store or projection
write directly, and its ``list_expired`` lookup is SELECT-only. The canonical operation is used
unchanged, so the §S6 guarantees hold exactly: only expired grants go, every removal carries the
operator authorization, and the deletion is reproducible from the event log. The console adds no path
around the prune operation, only the operator seat in front of it.
"""

import time

from devharness.cli.sign import operator_identity
from devharness.maintenance.prune import expired_trust_grants, prune_expired_trust_grants


class EmptyPruneReason(ValueError):
    """Raised when authorizing a prune without a reason — the operator authorization must carry one."""


class ConsolePrune:
    """Operator-driven authorized prune of expired trust grants, recorded through ``EventBus.emit_sync``.

    Constructed against the console connection and its ``EventBus`` writer (the emit-only write path).
    ``list_expired`` surfaces the expired grants an authorized prune would remove (SELECT-only);
    ``prune`` presses the operator authorization through the canonical
    ``maintenance.prune.prune_expired_trust_grants`` operation, attributing the recorded
    ``trust_grant_pruned`` events to the operator. ``operator`` defaults to the harness operator identity
    (``DEVHARNESS_OPERATOR`` env, else ``git config user.name``) and can be overridden per instance or per
    call — mirroring ``ConsoleSignoff`` / ``ConsoleTaskDecision``.
    """

    def __init__(self, conn, writer, *, operator=None, now_millis=None):
        self._conn = conn
        self._writer = writer  # an EventBus — emit_sync is the only sanctioned write path
        self._operator = operator
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))

    def _resolve_operator(self, operator) -> str:
        return operator or self._operator or operator_identity()

    def list_expired(self) -> list:
        """Return the expired, non-revoked trust grants an authorized prune would remove (SELECT-only).

        Delegates to the canonical ``maintenance.prune.expired_trust_grants`` over the console
        connection at the current time — the same set the dry-run ``devharness prune`` CLI lists. Each
        row is ``(grant_row_id, role_name, task_class, granted_at_millis)``. No event-store or
        projection write.
        """
        return expired_trust_grants(self._conn, at_millis=self._now_millis())

    def prune(self, reason, *, operator=None) -> int:
        """Authorize the prune of every expired trust grant; return the count pruned.

        The console equivalent of ``devharness prune --confirm --reason TEXT``: routes through the
        canonical ``maintenance.prune.prune_expired_trust_grants``, recording one operator-attributed
        ``trust_grant_pruned`` event per expired grant (the operator is the ``pruned_by`` authorizer).
        Requires a ``reason`` — the operator authorization — and refuses a blank one
        (``EmptyPruneReason``), so a vacuous authorization never reaches the canonical operation.
        """
        reason = (reason or "").strip()
        if not reason:
            raise EmptyPruneReason("authorizing a prune requires a reason (the operator authorization)")
        operator = self._resolve_operator(operator)
        return prune_expired_trust_grants(
            self._conn, self._writer, operator, reason, now_millis=self._now_millis
        )


__all__ = ["ConsolePrune", "EmptyPruneReason"]
