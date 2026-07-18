"""ACI shell action (B2.3).

A structured run_command tool. The destructive-command gate (B2.1) runs before any
execution; blocklisted commands are refused with the gate's deny envelope.
"""

import subprocess

from devharness.aci.host_exec import require_host_execution_authorized
from devharness.gates.base import GateDeny
from devharness.gates.destructive import DestructiveCommandGate


class DestructiveCommandRefused(RuntimeError):
    """Raised when a command matches the destructive-command blocklist."""

    def __init__(self, deny: GateDeny):
        super().__init__(deny.reason)
        self.deny = deny


class ShellActions:
    def __init__(self, *, worktree, sandbox_launcher=None):
        self.worktree = worktree
        # #1a (rev 0.3.24): when set, shell commands run through the §S5 SandboxLauncher's isolation
        # instead of a host subprocess, so out-of-worktree host writes (absolute-path commands) are
        # contained. Default None = host execution (the prior behaviour; the realized-diff scope check
        # remains the host-side enforcement).
        self.sandbox_launcher = sandbox_launcher

    def run_command(self, command_string: str) -> dict:
        result = DestructiveCommandGate().check({"command_string": command_string})
        if isinstance(result, GateDeny):
            raise DestructiveCommandRefused(result)
        if self.sandbox_launcher is not None:
            sb = self.sandbox_launcher.exec(["sh", "-c", command_string], cwd=self.worktree.path)
            return {"command": command_string, "returncode": sb.returncode,
                    "stdout": sb.stdout, "stderr": sb.stderr, "contained": sb.contained}
        # L4-1 (rev 0.3.35): unsandboxed host execution is fail-closed — a host subprocess is not contained,
        # so it runs only with explicit operator authorization (DEVHARNESS_ALLOW_HOST_SHELL=1).
        require_host_execution_authorized("shell command")
        proc = subprocess.run(
            command_string, shell=True, cwd=self.worktree.path, capture_output=True, text=True
        )
        return {
            "command": command_string,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
            "contained": False,
        }
