"""#M5: run the operator CLIs as the real `python -m` subprocess.

The existing CLI tests call the inner functions (sign_spec/answer_question) with a bus passed in —
they never run main(), so a regression INSIDE main() (no __main__ guard, or a bare registry-less
EventBus) would re-pass CI. These tests exercise the real entry point and assert the PROJECTION is
updated (which only happens if main() routes through the registry-equipped projected_bus).
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
sys.path.insert(0, str(RUNTIME))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _env(db_path, **extra):
    return {**os.environ, "PYTHONPATH": str(RUNTIME), "DEVHARNESS_DB": str(db_path), **extra}


def _projected_bus(conn):
    reg = ProjectionRegistry()
    register_handlers(reg)
    return EventBus(conn, reg)


def test_sign_cli_subprocess_emits_and_projects(tmp_path):
    db = tmp_path / "d.db"
    conn = sqlite3.connect(str(db))
    migrate(conn)
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES ('s1', 'spec', 1, '{}', 'c', 1, 0)"
    )
    conn.commit()
    conn.close()

    result = subprocess.run(
        [sys.executable, "-m", "devharness.cli.sign", "s1"],
        env=_env(db, DEVHARNESS_OPERATOR="alice"), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='spec_signed'").fetchone()[0] == 1
    # the projection is updated ONLY if main() used the registry-equipped bus (the #defect-3 guard)
    assert conn.execute("SELECT signed_by FROM proj_signed_spec WHERE spec_id='s1'").fetchone() == ("alice",)


def test_answer_cli_subprocess_emits_and_projects(tmp_path):
    db = tmp_path / "d.db"
    conn = sqlite3.connect(str(db))
    migrate(conn)
    _projected_bus(conn).emit_sync(
        "question_asked",
        {"research_id": "c", "question_id": "c-q0", "question_text": "scope?"},
        correlation_id="c",
    )
    conn.close()

    result = subprocess.run(
        [sys.executable, "-m", "devharness.cli.answer", "c-q0", "the whole repo"],
        env=_env(db), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='question_answered'").fetchone()[0] == 1
    assert conn.execute("SELECT answered FROM proj_questions WHERE question_id='c-q0'").fetchone() == (1,)


def test_sign_cli_subprocess_refuses_unknown_spec(tmp_path):
    db = tmp_path / "d.db"
    conn = sqlite3.connect(str(db))
    migrate(conn)
    conn.close()
    result = subprocess.run(
        [sys.executable, "-m", "devharness.cli.sign", "nope"],
        env=_env(db), capture_output=True, text=True,
    )
    assert result.returncode == 1  # main() ran and refused (not a silent no-op exit 0)
    assert "refused" in result.stderr
