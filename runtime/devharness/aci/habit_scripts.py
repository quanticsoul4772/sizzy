"""Habit scripts (B2.3).

Re-usable sequences composed of ACI actions, so repeated work is a named script, not
ad-hoc shell. The registry is the sole writer (single-write enforcement).
"""


class HabitScriptRegistrationError(RuntimeError):
    """Raised when registering a habit-script name that is already registered."""


HABIT_SCRIPTS: dict[str, object] = {}


def register_habit_script(name: str, fn) -> None:
    if name in HABIT_SCRIPTS:
        raise HabitScriptRegistrationError(f"habit script {name!r} already registered")
    HABIT_SCRIPTS[name] = fn


def stage_and_commit(aci: dict, message: str) -> dict:
    """Stage all changes and commit (composes the shell action). Purges bytecode caches first
    (rev 0.3.58) — a worker committing mid-task after running tests would otherwise make caches
    TRACKED, defeating the downstream untracked-cache purges at the harness's own git surfaces."""
    from devharness.worktree.hygiene import purge_bytecode_caches

    shell = aci["shell"]
    purge_bytecode_caches(shell.worktree.path)
    shell.run_command("git add -A")
    return shell.run_command(f'git commit -m "{message}"')


def run_pytest_and_report(aci: dict) -> dict:
    """Run the test suite and return the structured result (composes the test runner)."""
    return aci["test_runner"].run_tests()


register_habit_script("stage_and_commit", stage_and_commit)
register_habit_script("run_pytest_and_report", run_pytest_and_report)
