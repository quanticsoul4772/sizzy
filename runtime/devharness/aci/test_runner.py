"""ACI test-runner action (B2.3).

A structured run_tests tool. Runs the configured test command for the task class
(pytest / cargo test / npm test) and returns structured results.
"""

import subprocess

from devharness.aci.host_exec import require_host_execution_authorized

DEFAULT_TEST_COMMANDS = {
    "pytest": ["pytest", "-q"],
    "cargo": ["cargo", "test"],
    "npm": ["npm", "test"],
}


class TestRunnerActions:
    __test__ = False  # not a pytest test class (name starts with "Test")

    def __init__(self, *, worktree, default_command=None, sandbox_launcher=None):
        self.worktree = worktree
        self.default_command = default_command or DEFAULT_TEST_COMMANDS["pytest"]
        self.sandbox_launcher = sandbox_launcher  # #1a (rev 0.3.24): §S5 sandbox tier when set

    def run_tests(self, test_command=None) -> dict:
        command = test_command or self.default_command
        if self.sandbox_launcher is not None:
            sb = self.sandbox_launcher.exec(list(command), cwd=self.worktree.path)
            return {"command": command, "returncode": sb.returncode, "passed": sb.returncode == 0,
                    "stdout": sb.stdout, "stderr": sb.stderr, "contained": sb.contained}
        # L4-1 (rev 0.3.35): unsandboxed host execution is fail-closed (see aci/host_exec.py).
        require_host_execution_authorized("test run")
        proc = subprocess.run(command, cwd=self.worktree.path, capture_output=True, text=True)
        return {
            "command": command,
            "returncode": proc.returncode,
            "passed": proc.returncode == 0,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
            "contained": False,
        }
