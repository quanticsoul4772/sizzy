"""B2.6: done-is-earned — completed requires verifier pass AND reviewer cert."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.task_lifecycle.base import TaskLifecycle
from devharness.task_lifecycle.done_is_earned import DoneNotEarned, can_complete, complete


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    lifecycle = TaskLifecycle()
    lifecycle.transition("t1", "queued", "running", bus, conn)
    return conn, bus, lifecycle


def _emit_pass(bus):
    bus.emit_sync("verifier_outcome", {"task_id": "t1", "verifier": "test_suite", "passed": True, "detail": "", "evidence": {}}, correlation_id="c")


def _emit_cert(bus):
    bus.emit_sync("reviewer_certified", {"task_id": "t1", "reviewer_session_id": "s", "evidence": {}, "correlation_id": "c", "certified_at_millis": 1}, correlation_id="c")


def test_refuses_without_anything():
    conn, bus, lifecycle = _setup()
    assert can_complete("t1", conn) is False
    with pytest.raises(DoneNotEarned):
        complete("t1", lifecycle, conn, bus)


def test_refuses_with_only_verifier_pass():
    conn, bus, lifecycle = _setup()
    _emit_pass(bus)
    assert can_complete("t1", conn) is False
    with pytest.raises(DoneNotEarned):
        complete("t1", lifecycle, conn, bus)


def test_refuses_with_only_reviewer_cert():
    conn, bus, lifecycle = _setup()
    _emit_cert(bus)
    with pytest.raises(DoneNotEarned):
        complete("t1", lifecycle, conn, bus)


def test_allows_with_both():
    conn, bus, lifecycle = _setup()
    _emit_pass(bus)
    _emit_cert(bus)
    assert can_complete("t1", conn) is True
    complete("t1", lifecycle, conn, bus)
    assert lifecycle.state("t1") == "completed"


def test_a_failed_verifier_does_not_count_as_pass():
    conn, bus, lifecycle = _setup()
    bus.emit_sync("verifier_outcome", {"task_id": "t1", "verifier": "test_suite", "passed": False, "detail": "x", "evidence": {}}, correlation_id="c")
    _emit_cert(bus)
    assert can_complete("t1", conn) is False


def _emit_started(bus):
    bus.emit_sync("task_started", {"task_id": "t1", "role": "developer", "worktree_path": "/w",
                                   "correlation_id": "c", "started_at_millis": 1}, correlation_id="c")


def _emit_fail(bus):
    bus.emit_sync("verifier_outcome", {"task_id": "t1", "verifier": "test_suite", "passed": False, "detail": "x", "evidence": {}}, correlation_id="c")


def test_cross_attempt_evidence_does_not_earn_done(tmp_path):
    # Inv 5 across a re-drive: attempt 1 passes the verifier but is not completed (rejected); attempt 2
    # (a re-drive — new task_started) FAILS the verifier yet emits a reviewer cert. The earned-twice check
    # must NOT mix attempt-1's verifier pass with attempt-2's cert: the current attempt has no pass.
    conn, bus, lifecycle = _setup()
    _emit_started(bus); _emit_pass(bus)          # attempt 1: started, verifier passed (not completed)
    _emit_started(bus); _emit_fail(bus); _emit_cert(bus)  # attempt 2 (re-drive): started, FAILED, certified
    assert can_complete("t1", conn) is False
    with pytest.raises(DoneNotEarned):
        complete("t1", lifecycle, conn, bus)


def test_same_attempt_evidence_earns_done():
    # both the verifier pass AND the cert occur after the (single) task_started -> the current attempt earns it
    conn, bus, lifecycle = _setup()
    _emit_started(bus); _emit_pass(bus); _emit_cert(bus)
    assert can_complete("t1", conn) is True
    complete("t1", lifecycle, conn, bus)
    assert lifecycle.state("t1") == "completed"
