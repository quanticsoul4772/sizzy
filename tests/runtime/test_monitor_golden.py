"""Golden regression guard for the invariant-monitor checks (locks in the rev-0.3.93 re-drive fix).

The Inv-10/Inv-5 re-drive blind spots shipped because the tests only exercised trivial single-attempt
shapes. This fixture reproduces the exact real-`var/*.db` multi-attempt patterns that the pre-0.3.93 naive
checks (`len(terminals) > 1`, global `can_complete`) FALSE-flagged, and asserts `all_violations` reports
EXACTLY the three genuine violations and nothing else. A future change that re-introduces a false positive
on a legitimate re-drive — or that stops catching a genuine double/orphan/unearned — fails this test loudly.
Reuses `all_violations` verbatim (the same function the live monitor + the `devharness sweep` CLI call).
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cli import sweep
from devharness.cli._bus import projected_bus
from devharness.migrate import migrate
from devharness.monitor.checks import all_violations


def _started(bus, tid):
    bus.emit_sync("task_started", {"task_id": tid, "role": "developer", "worktree_path": "/w",
                                   "correlation_id": tid, "started_at_millis": 1}, correlation_id=tid)


def _terminal(bus, tid, outcome):
    bus.emit_sync("terminal_outcome", {"task_id": tid, "outcome": outcome, "detail": "", "reason": "",
                                       "correlation_id": tid, "terminated_at_millis": 2}, correlation_id=tid)


def _earn(bus, tid):
    bus.emit_sync("verifier_outcome", {"task_id": tid, "verifier": "v", "passed": True, "detail": "",
                                       "evidence": ""}, correlation_id=tid)
    bus.emit_sync("reviewer_certified", {"task_id": tid, "reviewer_session_id": "r", "evidence": "",
                                         "correlation_id": tid, "certified_at_millis": 2}, correlation_id=tid)


def _build(bus):
    # --- CLEAN: the real-store re-drive / retry / abort shapes the pre-0.3.93 check false-flagged ---
    # A — rejected x4 -> completed (pgharness-disc-t0)
    for _ in range(4):
        _started(bus, "A"); _terminal(bus, "A", "rejected")
    _started(bus, "A"); _earn(bus, "A"); _terminal(bus, "A", "completed")
    # B — rejected -> rejected (csvlite-t2)
    _started(bus, "B"); _terminal(bus, "B", "rejected")
    _started(bus, "B"); _terminal(bus, "B", "rejected")
    # C — aborted -> start -> completed (r1-t2, rev-0.3.86 abort-of-never-started)
    _terminal(bus, "C", "aborted")
    _started(bus, "C"); _earn(bus, "C"); _terminal(bus, "C", "completed")
    # D — start,start,earn,completed (non-terminal retry / transient_sdk_glitch)
    _started(bus, "D"); _started(bus, "D"); _earn(bus, "D"); _terminal(bus, "D", "completed")
    # E — attempt1 rejected, attempt2 earn+completed, attempt3 rejected (pgharness-val2-t0, Inv-5 case)
    _started(bus, "E"); _terminal(bus, "E", "rejected")
    _started(bus, "E"); _earn(bus, "E"); _terminal(bus, "E", "completed")
    _started(bus, "E"); _terminal(bus, "E", "rejected")
    # --- GENUINE violations that must still flag ---
    # F — start,earn,completed,completed: a real double-terminal within one attempt (Inv 10)
    _started(bus, "F"); _earn(bus, "F"); _terminal(bus, "F", "completed"); _terminal(bus, "F", "completed")
    # G — start,rejected,start: the latest attempt orphaned (Inv 10 liveness; store quiesced, no lock)
    _started(bus, "G"); _terminal(bus, "G", "rejected"); _started(bus, "G")
    # H — start,completed with no verifier/reviewer: unearned completion (Inv 5)
    _started(bus, "H"); _terminal(bus, "H", "completed")


_EXPECTED = {(10, "F"), (10, "G"), (5, "H")}


def _golden_store(path):
    conn = sqlite3.connect(str(path))
    migrate(conn)
    _build(projected_bus(conn))
    conn.commit()
    return conn


def test_all_violations_reports_exactly_the_genuine_set(tmp_path):
    conn = _golden_store(tmp_path / "golden.db")
    got = {(v.invariant_number, v.task_id) for v in all_violations(conn, include_orphans=True)}
    # EQUALITY, not membership: a new false positive (A–E) OR a missed genuine one both fail here.
    assert got == _EXPECTED, f"drift: {got ^ _EXPECTED}"


def test_sweep_cli_over_the_golden_store_matches(tmp_path, capsys):
    db = tmp_path / "golden.db"
    _golden_store(db).close()
    rc = sweep.main([str(db)])
    out = capsys.readouterr().out
    assert rc == 1
    for tid in ("F", "G", "H"):
        assert f"task={tid}" in out
    assert "task=A" not in out and "task=E" not in out  # no re-drive false positive leaks into the report
