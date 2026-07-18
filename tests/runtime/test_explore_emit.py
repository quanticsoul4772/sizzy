"""B1.5: run_and_emit persists the artifact and emits explore_pass_completed."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.explore.runner import run_and_emit
from devharness.migrate import migrate


def test_run_and_emit_persists_and_emits(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\ndependencies=["pytest"]\n')

    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)

    artifact_id = run_and_emit(str(tmp_path), "corr-1", bus, conn)

    row = conn.execute(
        "SELECT artifact_type, correlation_id, payload_json FROM artifacts WHERE artifact_id = ?", (artifact_id,)
    ).fetchone()
    assert row[0] == "explore_pass"
    assert row[1] == "corr-1"
    payload = json.loads(row[2])
    assert payload["explore_pass_id"] == artifact_id

    event = conn.execute(
        "SELECT correlation_id, payload FROM events WHERE event_type = 'explore_pass_completed'"
    ).fetchone()
    assert event[0] == "corr-1"
    assert json.loads(event[1])["summary_ref"] == artifact_id
