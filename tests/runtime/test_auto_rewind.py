"""B2.6: verifier failure auto-rewinds (clean) to baseline and rejects the task."""

import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.checkpoint.base import take_checkpoint
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.task_lifecycle.auto_rewind import on_verifier_failure
from devharness.task_lifecycle.base import TaskLifecycle, TaskLifecycleViolation
from devharness.verifier.base import Verifier, VerifierFailed
from devharness.verifier.registry import FALSIFIERS, register_verifier
from devharness.verifier.runner import run_verifier
from devharness.worktree.isolate import create_worktree, discard_worktree


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "README.md").write_text("hi\n")
    run("add", "-A")
    run("commit", "-m", "init")
    return repo


def _baseline(tmp_path):
    repo = _git_repo(tmp_path)
    worktree = create_worktree("t1", str(repo))
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    checkpoint = take_checkpoint("t1", worktree.path, "c", bus, conn)
    lifecycle = TaskLifecycle()
    lifecycle.transition("t1", "queued", "running", bus, conn)
    return conn, bus, lifecycle, checkpoint, worktree


def test_on_verifier_failure_clean_rewind_and_reject(tmp_path):
    conn, bus, lifecycle, checkpoint, worktree = _baseline(tmp_path)
    readme = Path(worktree.path) / "README.md"
    scratch = Path(worktree.path) / "scratch.txt"
    readme.write_text("changed\n")  # tracked change
    scratch.write_text("untracked\n")  # untracked file

    on_verifier_failure("t1", lifecycle, checkpoint, bus, conn)

    assert readme.read_text() == "hi\n"  # tracked restored
    assert not scratch.exists()  # untracked removed by git clean -fd
    assert lifecycle.state("t1") == "rejected"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='rewind_performed'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 1
    discard_worktree(worktree)


def test_run_verifier_failure_auto_triggers_rewind(tmp_path):
    conn, bus, lifecycle, checkpoint, worktree = _baseline(tmp_path)

    class _FailVerifier(Verifier):
        name = "_b26_fail"

        async def verify(self, context):
            return VerifierFailed(name=self.name, reason="nope")

    if "_b26_fail" not in FALSIFIERS:
        register_verifier("_b26_fail", _FailVerifier())

    result = asyncio.run(
        run_verifier("_b26_fail", {"task_id": "t1", "correlation_id": "c"}, bus, conn, lifecycle=lifecycle, checkpoint=checkpoint)
    )
    assert isinstance(result, VerifierFailed)
    assert lifecycle.state("t1") == "rejected"  # auto-rewind fired
    discard_worktree(worktree)


# --- Option 1: bounded spec-claim auto-retry is non-terminal until exhausted (one terminal per task) ---

def test_lifecycle_reset_allows_rerun_after_terminal(tmp_path):
    # the auto-retry crash regression: a rejected task cannot re-transition queued->running, but after
    # reset() (the non-terminal retryable rewind) it can, so the next attempt runs.
    conn, bus, lifecycle, checkpoint, worktree = _baseline(tmp_path)
    lifecycle.transition("t1", "running", "rejected", bus, conn)  # terminal
    with pytest.raises(TaskLifecycleViolation):
        lifecycle.transition("t1", "queued", "running", bus, conn)
    lifecycle.reset("t1")
    lifecycle.transition("t1", "queued", "running", bus, conn)  # now legal
    assert lifecycle.state("t1") == "running"
    discard_worktree(worktree)


def test_retryable_failure_rewinds_non_terminal(tmp_path):
    # a retryable spec-claim rewind emits NO terminal_outcome and resets the lifecycle so the next attempt
    # can re-run; only the final attempt's reject is terminal (one terminal per task, Invariant 10).
    conn, bus, lifecycle, checkpoint, worktree = _baseline(tmp_path)
    on_verifier_failure("t1", lifecycle, checkpoint, bus, conn, retryable=True)
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 0
    assert lifecycle.state("t1") == "queued"  # reset -> default
    lifecycle.transition("t1", "queued", "running", bus, conn)  # the retry's transition is legal
    discard_worktree(worktree)


def _register_fail(name, reason):
    class _F(Verifier):
        async def verify(self, context):
            return VerifierFailed(name=name, reason=reason)
    _F.name = name
    if name not in FALSIFIERS:
        register_verifier(name, _F())


def test_run_verifier_retryable_spec_claim_no_terminal(tmp_path):
    conn, bus, lifecycle, checkpoint, worktree = _baseline(tmp_path)
    _register_fail("_sc_retry", "spec_claim axis failed: deviated")
    asyncio.run(run_verifier("_sc_retry", {"task_id": "t1", "correlation_id": "c"}, bus, conn,
                             lifecycle=lifecycle, checkpoint=checkpoint, terminal_on_fail=False))
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 0
    assert lifecycle.state("t1") == "queued"  # non-terminal, reset for the retry
    discard_worktree(worktree)


def test_run_verifier_final_attempt_spec_claim_is_terminal(tmp_path):
    conn, bus, lifecycle, checkpoint, worktree = _baseline(tmp_path)
    _register_fail("_sc_final", "spec_claim axis failed: deviated")
    asyncio.run(run_verifier("_sc_final", {"task_id": "t1", "correlation_id": "c"}, bus, conn,
                             lifecycle=lifecycle, checkpoint=checkpoint, terminal_on_fail=True))
    assert lifecycle.state("t1") == "rejected"  # final attempt -> terminal
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 1
    discard_worktree(worktree)


def test_run_verifier_non_spec_claim_is_terminal_even_when_retry_allowed(tmp_path):
    # only a spec_claim deviation retries; a plain test failure is terminal even on a non-final attempt
    conn, bus, lifecycle, checkpoint, worktree = _baseline(tmp_path)
    _register_fail("_test_fail_nt", "test_suite: 1 failed")
    asyncio.run(run_verifier("_test_fail_nt", {"task_id": "t1", "correlation_id": "c"}, bus, conn,
                             lifecycle=lifecycle, checkpoint=checkpoint, terminal_on_fail=False))
    assert lifecycle.state("t1") == "rejected"  # not spec_claim -> terminal despite terminal_on_fail=False
    discard_worktree(worktree)


def test_run_verifier_retryable_test_coverage_no_terminal(tmp_path):
    # a missing-test-coverage failure is exactly as self-correctable as a spec_claim deviation (rev 0.3.49)
    conn, bus, lifecycle, checkpoint, worktree = _baseline(tmp_path)
    _register_fail("_tc_retry", "test_coverage axis failed: realized diff adds no new test function")
    asyncio.run(run_verifier("_tc_retry", {"task_id": "t1", "correlation_id": "c"}, bus, conn,
                             lifecycle=lifecycle, checkpoint=checkpoint, terminal_on_fail=False))
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 0
    assert lifecycle.state("t1") == "queued"
    discard_worktree(worktree)


def test_run_verifier_test_suite_axis_reason_is_not_retryable(tmp_path):
    # precision guard: a real test_suite axis failure must stay terminal even with retries available —
    # only spec_claim/test_coverage (self-correctable) axes retry.
    conn, bus, lifecycle, checkpoint, worktree = _baseline(tmp_path)
    _register_fail("_ts_axis", "test_suite axis failed: 1 failed")
    asyncio.run(run_verifier("_ts_axis", {"task_id": "t1", "correlation_id": "c"}, bus, conn,
                             lifecycle=lifecycle, checkpoint=checkpoint, terminal_on_fail=False))
    assert lifecycle.state("t1") == "rejected"
    discard_worktree(worktree)
