"""B2.4: WriteAttempted/WriteApplied typed; editor emits through the catalog; EVENT_TYPES is 24."""

import json
import sqlite3
import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.aci.editor import EditorActions, ScopeViolation
from devharness.events import registry as ev
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.worktree.isolate import Worktree


def test_write_events_registered_with_fields():
    assert "write_attempted" in ev.EVENT_TYPES and "write_applied" in ev.EVENT_TYPES
    wa = msgspec.convert(
        {"task_id": "t", "worktree_path": "/w", "target_path": "a.py", "action_kind": "write_file",
         "correlation_id": "c", "attempted_at_millis": 1},
        ev.WriteAttempted,
    )
    assert wa.action_kind == "write_file"
    ok = msgspec.convert(
        {"task_id": "t", "worktree_path": "/w", "target_path": "a.py", "action_kind": "append_to_file",
         "correlation_id": "c", "applied_at_millis": 2},
        ev.WriteApplied,
    )
    assert ok.applied_at_millis == 2


def test_event_types_count_at_least_24():
    # B2.4 brought the catalog to 24; B2.5 adds reviewer_certified/reviewer_rejected.
    assert len(ev.EVENT_TYPES) >= 24


def test_editor_emits_typed_payloads(tmp_path):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    editor = EditorActions(
        worktree=Worktree("t1", str(tmp_path), str(tmp_path)), scope_boundary=["src/**"],
        event_bus=EventBus(conn), conn=conn, correlation_id="c", task_id="t1", now_millis=lambda: 9,
    )
    # B2.8: a successful write emits write_attempted (predicted_success) + write_applied (observed_success)
    editor.write_file("src/main.py", "x = 1\n", predicted_success=0.8)
    applied = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='write_applied'").fetchone()[0])
    assert applied["target_path"] == "src/main.py" and applied["action_kind"] == "write_file" and applied["applied_at_millis"] == 9
    assert applied["observed_success"] is True
    success_attempt = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='write_attempted' ORDER BY seq DESC LIMIT 1").fetchone()[0])
    assert success_attempt["target_path"] == "src/main.py" and success_attempt["predicted_success"] == 0.8

    # a refused write emits write_attempted only (no write_applied -> observed False at calibration time)
    with pytest.raises(ScopeViolation):
        editor.write_file("tests/x.py", "y = 2\n")
    refused_attempt = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='write_attempted' ORDER BY seq DESC LIMIT 1").fetchone()[0])
    assert refused_attempt["target_path"] == "tests/x.py" and refused_attempt["action_kind"] == "write_file"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='write_applied'").fetchone()[0] == 1  # only the success
