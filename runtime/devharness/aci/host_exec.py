"""Host-execution authorization — the L4-1 fail-closed guard (rev 0.3.35).

The developer's ACI shell (`ShellActions.run_command`) and test-runner (`TestRunnerActions.run_tests`)
run commands on the HOST whenever no §S5 `SandboxLauncher` is set. A host subprocess gives a
(possibly prompt-injected) worker arbitrary host reach — network exfil, reading host secrets,
absolute-path writes — that neither the realized-diff scope check nor the destructive-command blocklist
can contain (a blocklist of ~11 substrings misses `curl … | sh`, `cat ~/.ssh/id_rsa`, and the rest).

So unsandboxed host execution is **fail-closed**: it runs only when the operator has explicitly
authorized it (``DEVHARNESS_ALLOW_HOST_SHELL=1`` — "I am on a trusted host", commitment 14) OR a sandbox
launcher is set. Without either, the ACI refuses — the dangerous path is no longer the silent default.
"""

import os


class HostExecutionRefused(RuntimeError):
    """Unsandboxed host execution is not authorized (no sandbox launcher + no operator opt-in)."""


def host_execution_authorized() -> bool:
    return os.environ.get("DEVHARNESS_ALLOW_HOST_SHELL") == "1"


def require_host_execution_authorized(action: str) -> None:
    """Raise HostExecutionRefused unless the operator has authorized unsandboxed host execution. Callers
    invoke this only on the host path (no sandbox launcher set)."""
    if not host_execution_authorized():
        raise HostExecutionRefused(
            f"refusing unsandboxed host {action}: set DEVHARNESS_ALLOW_HOST_SHELL=1 to authorize host "
            "execution on a trusted host (commitment 14), or run the developer with a §S5 sandbox launcher "
            "(DeveloperRole(sandbox_launcher=…)). A host subprocess is not contained — the destructive "
            "blocklist + realized-diff scope check do not stop network/secret-read/absolute-path commands."
        )
