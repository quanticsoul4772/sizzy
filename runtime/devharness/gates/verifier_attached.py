"""Verifier-attached gate (B2.2 semantic, §S2 verifier-attached gate).

Refuses a task whose verifier_ref is missing OR names a verifier that is not
registered in FALSIFIERS. (B2.1 shipped the structural-presence half; B2.2 makes it
semantic against the falsifier registry.)
"""

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate
from devharness.verifier.registry import FALSIFIERS


class VerifierAttachedGate(Gate):
    name = "verifier_attached_gate"

    def check(self, context: dict):
        planned = context.get("planned_task")
        verifier_ref = getattr(planned, "verifier_ref", None) if planned is not None else context.get("verifier_ref")
        if verifier_ref is None:
            return GateDeny(
                reason="Task verifier_ref is None",
                purpose="Verifier-first acceptance: a task cannot start without a declared verification plan (Invariant 5, §S3)",
                fix="Attach a verifier (a registered falsifier name) to the task before dispatch",
            )
        if verifier_ref not in FALSIFIERS:
            return GateDeny(
                reason=f"Task verifier_ref {verifier_ref} is not registered in FALSIFIERS",
                purpose="Verifier-first acceptance: the declared verifier must be a registered falsifier (Invariant 5, §S3)",
                fix="Set verifier_ref to a registered falsifier name, or register the verifier",
            )
        return GateOk()


register_gate("verifier_attached_gate", VerifierAttachedGate())
