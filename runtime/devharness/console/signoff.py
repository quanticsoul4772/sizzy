"""Operator console sign-off action — review the synthesized spec and sign or reject it.

The operator holds the spec sign-off gate, with no LLM agent in the seat: ``review``
surfaces the synthesized spec artifact for the operator to read (SELECT-only), ``sign``
records the operator's approval, and ``reject`` records a refusal with a reason. Both
decisions are recorded through ``EventBus.emit_sync`` — the console's sole sanctioned
write path — and attributed to the operator (the human in the seat, not an LLM).

``sign`` routes through the canonical ``cli.sign.sign_spec`` so the artifact's ``signed``
flag is set on the SAME path the ``devharness sign`` CLI uses, and ``spec_signed`` is
recorded with the operator as ``signer``. The ``spec_signed_gate`` (Invariant 4 /
commitment 12) then admits the build — the human sign-off gate is preserved exactly.
``reject`` records a ``spec_rejected`` event and leaves the artifact unsigned, so the gate
keeps refusing the build until the operator signs.

Lookups are SELECT-only; the console never writes the event store or a projection directly.
"""

import json
import time

from devharness.cli.sign import UnknownSpec, operator_identity, sign_spec

# The operator-attributed event recording a refusal at the sign-off gate. Its sibling on the
# approve path is the canonical ``spec_signed`` (emitted by ``sign_spec``).
SPEC_REJECTED_EVENT = "spec_rejected"


class EmptyRejectionReason(ValueError):
    """Raised when rejecting a spec without a reason — a refusal must carry one."""


class ConsoleSignoff:
    """Operator-driven sign-off actions, emitting operator-attributed events via emit_sync.

    Constructed against the console's connection and its ``EventBus`` writer (the emit-only
    write path). ``operator`` defaults to the harness operator identity
    (``DEVHARNESS_OPERATOR`` env, else ``git config user.name``) and can be overridden per
    instance or per call — mirroring ``ConsoleResearch``.
    """

    def __init__(self, conn, writer, *, operator=None, now_millis=None):
        self._conn = conn
        self._writer = writer  # an EventBus — emit_sync is the only sanctioned write path
        self._operator = operator
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))

    def _resolve_operator(self, operator) -> str:
        return operator or self._operator or operator_identity()

    def review(self, spec_id) -> dict:
        """Return the synthesized spec artifact payload for the operator to read.

        SELECT-only; raises ``UnknownSpec`` when no spec artifact carries that id.
        """
        payload = self._spec_payload(spec_id)
        if payload is None:
            raise UnknownSpec(f"no spec artifact with id {spec_id!r}")
        return payload

    def sign(self, spec_id, *, operator=None) -> str:
        """Sign the reviewed spec via the canonical sign path; return the spec_id.

        Routes through ``cli.sign.sign_spec``, so the artifact's ``signed`` flag is set and
        ``spec_signed`` is recorded with the operator as ``signer`` — the ``spec_signed_gate``
        then admits the build. Raises ``UnknownSpec`` for an unknown spec_id.
        """
        operator = self._resolve_operator(operator)
        return sign_spec(
            self._conn, self._writer, spec_id, operator=operator, now_millis=self._now_millis
        )

    def reject(self, spec_id, reason, *, operator=None) -> str:
        """Record an operator refusal of the spec; leave it unsigned. Return the spec_id.

        Emits ``spec_rejected`` (operator-attributed, carrying the reason) through
        ``emit_sync``, leaving the artifact unsigned so the ``spec_signed_gate`` keeps
        refusing the build. Raises ``UnknownSpec`` for an unknown spec_id and
        ``EmptyRejectionReason`` for a blank reason.
        """
        operator = self._resolve_operator(operator)
        correlation_id = self._correlation_for_spec(spec_id)
        if correlation_id is None:
            raise UnknownSpec(f"no spec artifact with id {spec_id!r}")
        reason = (reason or "").strip()
        if not reason:
            raise EmptyRejectionReason(f"rejecting spec {spec_id!r} requires a reason")
        self._writer.emit_sync(
            SPEC_REJECTED_EVENT,
            {
                "spec_id": spec_id,
                "operator": operator,  # operator-attributed (the human in the seat, not an LLM)
                "reason": reason,
                "rejected_at_millis": self._now_millis(),
            },
            correlation_id=correlation_id,
        )
        return spec_id

    # --- read-only lookups (SELECT-only; no event-store or projection writes) ---

    def _correlation_for_spec(self, spec_id):
        row = self._conn.execute(
            "SELECT correlation_id FROM artifacts WHERE artifact_id = ? AND artifact_type = 'spec'",
            (spec_id,),
        ).fetchone()
        return row[0] if row else None

    def _spec_payload(self, spec_id):
        row = self._conn.execute(
            "SELECT payload_json FROM artifacts WHERE artifact_id = ? AND artifact_type = 'spec'",
            (spec_id,),
        ).fetchone()
        return json.loads(row[0]) if row else None
