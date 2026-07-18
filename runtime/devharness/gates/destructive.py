"""Destructive-command gate (B2.1, §S2 destructive-command gate).

Refuses force-push, history rewrite, state wipe, and verification bypass. Matches a
command string against a blocklist of substrings.
"""

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate

BLOCKLIST = [
    "rm -rf",
    "git push --force",
    "git push -f",
    "git reset --hard",
    "git rebase -i",
    "--no-verify",
    "git filter-branch",
    "git clean -fd",
    "mkfs",
    "> /dev/sd",
    "dd if=",
]


class DestructiveCommandGate(Gate):
    name = "destructive_command_gate"

    def check(self, context: dict):
        command = context.get("command_string", "") or ""
        for pattern in BLOCKLIST:
            if pattern in command:
                return GateDeny(
                    reason=f"Command matches destructive pattern {pattern!r}: {command}",
                    purpose="Destructive-command gate: refuse force-push, history rewrite, state wipe (Commitment 9, §S2)",
                    fix="Use a non-destructive equivalent, or perform the operation manually outside the harness",
                )
        return GateOk()


register_gate("destructive_command_gate", DestructiveCommandGate())
