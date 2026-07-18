"""`devharness backfill <store>` — run the closed loop over a store's real history on a scratch COPY (rev
0.3.96). The original is never written; a historical orphan (the reviewer's defect case) must still produce
a candidate via the QuiescentFermata override.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cli import backfill
from devharness.cli._bus import projected_bus
from devharness.events.bus import verify_chain
from devharness.migrate import migrate


def _seed(path):
    conn = sqlite3.connect(str(path))
    migrate(conn)
    return conn, projected_bus(conn)


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


def _orphan_store(path):
    conn, bus = _seed(path)
    _started(bus, "t1")  # orphan: started, never terminated (a real store's t4 shape)
    conn.commit(); conn.close()


def test_orphan_store_backfills_a_signal_AND_a_candidate(tmp_path):
    """The mandatory defect case: the orphan holds the live fermata, so without the QuiescentFermata
    override the drain would produce 0 candidates. It must produce 1 signal + 1 pending candidate."""
    db = tmp_path / "orphan.db"
    _orphan_store(db)
    out = tmp_path / "orphan.backfilled.db"
    assert backfill.main([str(db), "--out", str(out)]) == 0
    c = sqlite3.connect(str(out))
    assert c.execute("SELECT COUNT(*) FROM events WHERE event_type='invariant_violated'").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM proj_gate_change_queue WHERE "
                     "signature_name='monitor_invariant_violated' AND review_state='pending'").fetchone()[0] == 1
    verify_chain(c)  # the copy's chain is intact (raises on break)
    c.close()


def test_original_store_is_never_written(tmp_path):
    db = tmp_path / "orphan.db"
    _orphan_store(db)
    before = sqlite3.connect(str(db))
    ev = before.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    before.close()

    backfill.main([str(db), "--out", str(tmp_path / "copy.db")])

    after = sqlite3.connect(str(db))
    assert after.execute("SELECT COUNT(*) FROM events").fetchone()[0] == ev  # no event appended
    assert after.execute("SELECT COUNT(*) FROM events WHERE event_type='invariant_violated'").fetchone()[0] == 0
    after.close()


def test_clean_store_backfills_nothing(tmp_path, capsys):
    db = tmp_path / "clean.db"
    conn, bus = _seed(db)
    _started(bus, "t1"); _earn(bus, "t1"); _terminal(bus, "t1", "completed")
    conn.commit(); conn.close()
    assert backfill.main([str(db), "--out", str(tmp_path / "copy.db")]) == 0
    assert "emitted 0 signal(s), created 0 candidate(s)" in capsys.readouterr().out


def test_missing_store_returns_2_and_creates_nothing(tmp_path, capsys):
    db = tmp_path / "nope.db"
    assert backfill.main([str(db)]) == 2
    assert not db.exists()
    assert "does not create" in capsys.readouterr().err


def test_dispatch_registered_in_main():
    from devharness.__main__ import _SUBCOMMANDS
    assert "backfill" in _SUBCOMMANDS
