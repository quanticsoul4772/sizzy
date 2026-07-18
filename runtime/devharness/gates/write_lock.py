"""Write-lock gate (B2.0, Invariant 1 / commitment 11).

Refuses a write-attempting transition when the single write lock is held by a
different role. Passes when the lock is free or when the requesting holder already
holds it.
"""

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate


class WriteLockGate(Gate):
    name = "write_lock_gate"

    def check(self, context: dict):
        conn = context["conn"]
        holder_role = context.get("holder_role")
        row = conn.execute("SELECT holder_role, correlation_id FROM proj_lock LIMIT 1").fetchone()
        if row is None or row[0] == holder_role:
            return GateOk()
        return GateDeny(
            reason=f"Write lock held by {row[0]} for correlation_id {row[1]}",
            purpose="Single-writer invariant: only one role edits code at a time (Invariant 1, Commitment 11)",
            fix="Wait for the holder to release the lock, or release it via the runtime lock API",
        )


register_gate("write_lock_gate", WriteLockGate())
