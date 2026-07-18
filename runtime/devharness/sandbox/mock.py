"""MockSandboxLauncher (B4.2.5) — the fail-closed in-process default.

Used in the CI matrix and on any non-Linux host without WSL. It establishes NO containment, so
``contained=False`` — the B4.3 sandbox gate denies when only the mock is available, satisfying SC-3
structurally (an out-of-sandbox launch fails, it does not warn).
"""

from devharness.sandbox.base import SandboxLauncher, SandboxResult

_NO_CONTAINMENT = "MockSandboxLauncher: no real containment available on this platform"


class MockSandboxLauncher(SandboxLauncher):
    name = "mock"

    def exec(self, command: list[str], cwd: str, timeout_seconds: int = 30) -> SandboxResult:
        # never runs the command — there is no isolation to run it inside
        return SandboxResult(returncode=-1, stdout="", stderr=_NO_CONTAINMENT, contained=False)
