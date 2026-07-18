"""Test-suite falsifier (B2.2) — runs a configured test command; exit 0 = pass.

A non-zero exit is only a real test failure if the runner actually RAN. A process that crashes on
launch (Windows STATUS_* fatal range, e.g. 0xC0000142 under process/desktop-heap pressure, or a
POSIX signal kill) returns a fatal code and produces NO test output — that says nothing about the
code, and scoring it as a failure rewinds good work. So a launch-crash is retried; only an exit
where the runner produced output is read as pass/fail.
"""

import subprocess
import time

from devharness.verifier.base import Verifier, VerifierFailed, VerifierOk
from devharness.verifier.registry import register_verifier

# Windows fatal exception range (STATUS_*): >= 0xC0000000. 0xC0000142 = STATUS_DLL_INIT_FAILED.
_WIN_FATAL_MIN = 0xC0000000


def _launch_crash(returncode: int, stdout: str) -> bool:
    """The runner never executed: a fatal OS-level exit (Windows STATUS_* range or POSIX signal)
    with no test output. A genuine test failure exits small (1-5) WITH a pytest summary."""
    if returncode == 0:
        return False
    fatal = returncode >= _WIN_FATAL_MIN or returncode < 0
    produced_output = bool((stdout or "").strip())
    return fatal and not produced_output


class TestSuiteVerifier(Verifier):
    name = "test_suite"
    _MAX_ATTEMPTS = 3

    async def verify(self, context: dict):
        command = context.get("test_command") or ["pytest", "-q"]
        proc = None
        for attempt in range(self._MAX_ATTEMPTS):
            proc = subprocess.run(command, cwd=context.get("cwd"), capture_output=True, text=True)
            if not _launch_crash(proc.returncode, proc.stdout):
                break  # the runner executed — this result is trustworthy
            time.sleep(2 * (attempt + 1))  # transient process/heap pressure — back off and retry
        evidence = {
            "command": command,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-2000:],
            "stderr": (proc.stderr or "")[-2000:],
            "attempts": attempt + 1,
        }
        if proc.returncode == 0:
            return VerifierOk(name=self.name, evidence=evidence)
        if _launch_crash(proc.returncode, proc.stdout):
            # still crashing on launch after retries: an infrastructure failure, NOT a test failure.
            # Raise so the run errors visibly instead of silently rewinding good work as "tests failed".
            raise RuntimeError(
                f"test runner failed to launch (exit {proc.returncode}, no output) after "
                f"{attempt + 1} attempts — infrastructure failure, not a test result"
            )
        # Surface the captured output tail in the reason so the failure is diagnosable in the event log (the
        # reason propagates into the verifier_outcome detail); evidence keeps the full captured streams.
        tail = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()[-1200:]
        reason = f"test command exited {proc.returncode}" + (f" — output tail:\n{tail}" if tail else "")
        return VerifierFailed(name=self.name, reason=reason, evidence=evidence)


register_verifier("test_suite", TestSuiteVerifier())
