"""SandboxLauncher interface + result type (B4.2.5, §S5)."""

from abc import ABC, abstractmethod

import msgspec


class SandboxResult(msgspec.Struct, frozen=True, kw_only=True):
    """The outcome of running a command inside (or attempting to contain it within) a sandbox.

    ``contained`` is True iff the launcher established real isolation around the command; False when
    containment failed or the launcher is the fail-closed mock. ``returncode`` is the sandboxed
    command's own exit code (distinct from a containment failure, which raises SandboxContainmentError).
    """
    returncode: int
    stdout: str
    stderr: str
    contained: bool


class SandboxContainmentError(RuntimeError):
    """The launcher could not establish containment (missing runtime, failed namespace setup, no
    SSH/config). Distinct from a non-zero exit code returned by the sandboxed command itself."""


class SandboxLauncher(ABC):
    """Runs a command under isolation. Identity is the enforced containment, not a prompt."""

    name: str = "sandbox_launcher"

    @abstractmethod
    def exec(self, command: list[str], cwd: str, timeout_seconds: int = 30) -> SandboxResult:
        """Run ``command`` with working directory ``cwd`` under a hard ``timeout_seconds`` wall clock."""
        ...
