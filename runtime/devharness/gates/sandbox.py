"""sandbox gate (§S5 OSS fear-map; real body B4.3).

Refuses execution outside the process-level sandbox (SC-3: an out-of-sandbox launch *fails*, not
warns). The gate is STRUCTURAL — it resolves the sandbox launcher (B4.2.5 SANDBOX_LAUNCHERS) and
denies when only the fail-closed MockSandboxLauncher is available (no real containment on this host).
It does NOT perform a probe exec at admission (that would be expensive on every dispatch); behavioral
SC-3 verification (a probe exec confirming containment) happens in the B4.8 acceptance pass against
both real launchers. Override: `sandbox_override` (e.g. CI, where no real sandbox is available).
"""

from devharness.gates.base import Gate, GateDeny, GateOk
from devharness.gates.registry import register_gate
from devharness.sandbox.mock import MockSandboxLauncher
from devharness.sandbox.registry import SANDBOX_LAUNCHERS, resolve_launcher


class SandboxGate(Gate):
    name = "sandbox"

    def check(self, context: dict):
        launcher = resolve_launcher(context.get("sandbox_launcher_preferred"))
        if isinstance(launcher, MockSandboxLauncher):
            if context.get("sandbox_override") is True:
                return GateOk(reason="sandbox_unavailable_with_override", evidence={"resolved_launcher": launcher.name})
            return GateDeny(
                reason="sandbox_unavailable: no real containment launcher resolved (mock only)",
                purpose="OSS work must run inside a real process-level sandbox (SC-3 — out-of-sandbox launch fails, not warns)",
                fix="Run on a host with WSL or a configured VPS launcher, or attach an approved sandbox_override",
                evidence={"resolved_launcher": launcher.name, "available_launchers": list(SANDBOX_LAUNCHERS.keys())},
            )
        return GateOk(reason="sandbox_available", evidence={"resolved_launcher": launcher.name})


register_gate("sandbox", SandboxGate())
