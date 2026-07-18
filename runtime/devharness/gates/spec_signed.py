"""Spec-signed gate (B1.3, Invariant 4 / commitment 12).

The state machine cannot advance toward BUILD from an unsigned spec. The gate
looks up the most recent spec artifact for the context's correlation_id and passes
only when it is signed.
"""

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate


class SpecSignedGate(Gate):
    name = "spec_signed_gate"

    def check(self, context: dict):
        conn = context["conn"]
        correlation_id = context["correlation_id"]
        row = conn.execute(
            "SELECT signed FROM artifacts "
            "WHERE artifact_type = 'spec' AND correlation_id = ? "
            "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1",
            (correlation_id,),
        ).fetchone()
        if row is not None and row[0] == 1:
            return GateOk()
        return GateDeny(
            reason=f"No signed spec artifact for correlation_id {correlation_id}",
            purpose="BUILD requires an operator-signed spec (Invariant 4, Commitment 12)",
            fix="Draft a spec via the research role and run `devharness sign <spec_id>` to sign it",
        )


register_gate("spec_signed_gate", SpecSignedGate())
