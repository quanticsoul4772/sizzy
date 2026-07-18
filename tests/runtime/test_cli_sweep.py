"""`devharness sweep <store>` — the read-only invariant-monitor diagnostic CLI (rev 0.3.94).

Strictly read-only: it reports violations over a store's whole log, emits nothing, mutates nothing.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cli import sweep
from devharness.cli._bus import projected_bus
from devharness.migrate import migrate


def _seed(path):
    conn = sqlite3.connect(str(path))
    migrate(conn)
    return conn, projected_bus(conn)


def _started(bus, tid, corr="c"):
    bus.emit_sync("task_started", {"task_id": tid, "role": "developer", "worktree_path": "/w",
                                   "correlation_id": corr, "started_at_millis": 1}, correlation_id=corr)


def _terminal(bus, tid, outcome="completed", corr="c"):
    bus.emit_sync("terminal_outcome", {"task_id": tid, "outcome": outcome, "detail": "", "reason": "",
                                       "correlation_id": corr, "terminated_at_millis": 2}, correlation_id=corr)


def _earn(bus, tid, corr="c"):
    bus.emit_sync("verifier_outcome", {"task_id": tid, "verifier": "v", "passed": True, "detail": "",
                                       "evidence": ""}, correlation_id=corr)
    bus.emit_sync("reviewer_certified", {"task_id": tid, "reviewer_session_id": "r", "evidence": "",
                                         "correlation_id": corr, "certified_at_millis": 2}, correlation_id=corr)


def test_dirty_store_reports_violation_and_returns_1(tmp_path, capsys):
    db = tmp_path / "dirty.db"
    conn, bus = _seed(db)
    _started(bus, "t1"); _terminal(bus, "t1", "completed"); _terminal(bus, "t1", "aborted")  # genuine double
    conn.commit(); conn.close()
    rc = sweep.main([str(db)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Inv 10" in out and "more than one" in out


def test_clean_store_returns_0(tmp_path, capsys):
    db = tmp_path / "clean.db"
    conn, bus = _seed(db)
    _started(bus, "t1"); _earn(bus, "t1"); _terminal(bus, "t1", "completed")
    conn.commit(); conn.close()
    rc = sweep.main([str(db)])
    assert rc == 0
    assert "clean" in capsys.readouterr().out


def test_redrive_store_is_clean_from_the_cli(tmp_path, capsys):
    """The rev-0.3.93 re-drive fix is reachable from the CLI: start,term,start,earn,term → clean."""
    db = tmp_path / "redrive.db"
    conn, bus = _seed(db)
    _started(bus, "t1"); _terminal(bus, "t1", "rejected")
    _started(bus, "t1"); _earn(bus, "t1"); _terminal(bus, "t1", "completed")
    conn.commit(); conn.close()
    assert sweep.main([str(db)]) == 0


def test_sweep_does_not_mutate_the_store(tmp_path):
    db = tmp_path / "dirty2.db"
    conn, bus = _seed(db)
    _started(bus, "t1"); _terminal(bus, "t1", "completed"); _terminal(bus, "t1", "aborted")
    conn.commit(); conn.close()
    before = sqlite3.connect(str(db))
    ev = before.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    mig = before.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    before.close()

    sweep.main([str(db)])

    after = sqlite3.connect(str(db))
    assert after.execute("SELECT COUNT(*) FROM events").fetchone()[0] == ev          # no event written
    assert after.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == mig  # no migrate
    assert after.execute("SELECT COUNT(*) FROM events WHERE event_type='invariant_violated'").fetchone()[0] == 0
    after.close()


def test_missing_store_returns_2_and_does_not_create_it(tmp_path, capsys):
    db = tmp_path / "nope.db"
    rc = sweep.main([str(db)])
    assert rc == 2
    assert not db.exists()  # never created
    assert "does not create" in capsys.readouterr().err


def test_dispatch_registered_in_main():
    from devharness.__main__ import _SUBCOMMANDS
    assert "sweep" in _SUBCOMMANDS
