"""#M4: the ACI write tools carry the worker's predicted_success, so the Brier signal isn't constant.

The live write path emitted a constant 0.5 because the MCP write_file/append_to_file tools dropped
predicted_success (the editor already records whatever it is given — tests pass 0.9). The tools now
read + clamp the worker's prediction via _pred and pass it through, so the calibration loop (H4/H5)
sees a real signal.
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.aci.editor import EditorActions
from devharness.aci.server import _pred
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.worktree.isolate import Worktree


def test_pred_clamps_and_defaults():
    assert _pred({"predicted_success": 0.83}) == 0.83
    assert _pred({}) == 0.5                       # absent -> default (the old constant)
    assert _pred({"predicted_success": 1.5}) == 1.0   # clamp high
    assert _pred({"predicted_success": -0.2}) == 0.0  # clamp low
    assert _pred({"predicted_success": "nan-ish"}) == 0.5  # invalid -> default


def test_editor_records_the_passed_prediction(tmp_path):
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    editor = EditorActions(worktree=Worktree("t1", str(tmp_path), str(tmp_path)),
                           scope_boundary=["src/**"], event_bus=EventBus(conn),
                           conn=conn, correlation_id="c", task_id="t1")
    editor.write_file("src/main.py", "x = 1\n", predicted_success=_pred({"predicted_success": 0.83}))

    payload = json.loads(conn.execute(
        "SELECT payload FROM events WHERE event_type='write_attempted'").fetchone()[0])
    assert payload["predicted_success"] == 0.83  # not the constant 0.5
