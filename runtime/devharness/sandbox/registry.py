"""SANDBOX_LAUNCHERS registry + launcher resolution (B4.2.5).

Single-write registry mapping a launcher name to its factory. resolve_launcher picks the binding by
environment: an explicit ``preferred`` wins (tests inject "mock"; B4.8 injects "wsl"/"vps"); otherwise
WSL is auto-selected when present, else the fail-closed mock. VPS is never auto-selected — opt in
explicitly so dev runs never make accidental network calls.
"""

from devharness.sandbox.base import SandboxLauncher
from devharness.sandbox.mock import MockSandboxLauncher
from devharness.sandbox.vps import VPSSandboxLauncher
from devharness.sandbox.wsl import WSLSandboxLauncher, detect_wsl

# name -> factory (callable returning a fresh launcher)
SANDBOX_LAUNCHERS: dict[str, object] = {
    "mock": MockSandboxLauncher,
    "wsl": WSLSandboxLauncher,
    "vps": VPSSandboxLauncher,
}


class UnknownLauncherError(KeyError):
    """Raised when resolve_launcher is asked for a name not in SANDBOX_LAUNCHERS."""


def resolve_launcher(preferred: str | None = None) -> SandboxLauncher:
    """Select the launcher to use. Explicit ``preferred`` wins; else auto-select WSL-or-mock."""
    if preferred is not None:
        if preferred not in SANDBOX_LAUNCHERS:
            raise UnknownLauncherError(preferred)
        return SANDBOX_LAUNCHERS[preferred]()
    if detect_wsl():
        return WSLSandboxLauncher()
    return MockSandboxLauncher()
