"""B2.0: the four graduated boot-checks pass and fail closed."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.gates import registry as gate_registry
import devharness.gates.write_lock  # noqa: F401  (registers the gate)
from devharness.migrate import migrate


def test_four_registered_under_c11_and_c5():
    names = boot.registered_check_names()
    for name in (
        "check_single_writer_lock_present",
        "check_concurrent_write_attempts_fail_closed",
        "check_correlation_id_coverage",
        "check_event_log_writer_singleton",
    ):
        assert name in names
    assert boot.REQUIRED_GATES["check_single_writer_lock_present"] == "C11"
    assert boot.REQUIRED_GATES["check_concurrent_write_attempts_fail_closed"] == "C11"
    assert boot.REQUIRED_GATES["check_correlation_id_coverage"] == "C5"
    assert boot.REQUIRED_GATES["check_event_log_writer_singleton"] == "C5"


def test_all_four_pass():
    assert boot.check_single_writer_lock_present() is True
    assert boot.check_concurrent_write_attempts_fail_closed() is True
    assert boot.check_correlation_id_coverage() is True
    assert boot.check_event_log_writer_singleton() is True


def test_lock_present_fails_closed_when_gate_unregistered(monkeypatch):
    monkeypatch.delitem(gate_registry.GATES, "write_lock_gate")
    with pytest.raises(boot.BootError):
        boot.check_single_writer_lock_present()


def test_correlation_coverage_fails_closed_on_bad_event():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    # plant an event with an empty correlation_id (bypassing the EventBus writer)
    conn.execute(
        "INSERT INTO events (event_id, correlation_id, event_type, payload, prev_hash, hash) "
        "VALUES ('e1', '', 'gate_fired', '{}', '', 'h')"
    )
    conn.commit()
    with pytest.raises(boot.BootError):
        boot.check_correlation_id_coverage(conn)


def test_writer_singleton_fails_closed_on_planted_insert(tmp_path):
    (tmp_path / "rogue.py").write_text('SQL = "INSERT INTO events (event_id) VALUES (1)"\n')
    with pytest.raises(boot.BootError):
        boot.check_event_log_writer_singleton(root=tmp_path)
