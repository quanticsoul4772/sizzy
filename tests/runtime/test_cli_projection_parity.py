"""Operator CLIs must emit through a registry-equipped bus (projected_bus) so the
live projections stay consistent with the event log (Invariant 8).

Regression for the defect where cli/{answer,sign,retro,memory} built a bare
EventBus(conn): the event was appended but its projection handler never ran, so
proj_signed_spec / proj_questions drifted and a from-scratch rebuild diverged.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cli._bus import projected_bus
from devharness.cli.answer import answer_question
from devharness.cli.sign import sign_spec
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import ParityError, check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry


def _registry():
    reg = ProjectionRegistry()
    register_handlers(reg)
    return reg


def _insert_spec(conn, artifact_id, correlation_id):
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, '{}', ?, 1, 0)",
        (artifact_id, correlation_id),
    )
    conn.commit()


def test_sign_via_projected_bus_updates_projection_live_and_keeps_parity():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    _insert_spec(conn, "spec-1", "corr-1")

    sign_spec(conn, projected_bus(conn), "spec-1", operator="alice")

    # proj_signed_spec is populated WITHOUT any manual rebuild
    assert conn.execute(
        "SELECT signed_by FROM proj_signed_spec WHERE spec_id='spec-1'"
    ).fetchone() == ("alice",)
    assert check_projection_rebuild_parity(conn, _registry()) is True


def test_answer_via_projected_bus_updates_projection_live_and_keeps_parity():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = projected_bus(conn)
    bus.emit_sync(
        "question_asked",
        {"research_id": "corr-1", "question_id": "corr-1-q0", "question_text": "scope?"},
        correlation_id="corr-1",
    )

    answer_question(conn, bus, "corr-1-q0", "the whole repo")

    assert conn.execute(
        "SELECT answered FROM proj_questions WHERE question_id='corr-1-q0'"
    ).fetchone() == (1,)
    assert check_projection_rebuild_parity(conn, _registry()) is True


def test_bare_eventbus_drifts_projection_and_breaks_parity():
    """The original defect: a registry-less bus appends the event but skips the
    projection handler, so the live state diverges from a rebuild."""
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    _insert_spec(conn, "spec-1", "corr-1")

    sign_spec(conn, EventBus(conn), "spec-1", operator="alice")  # bare bus — the bug

    assert conn.execute("SELECT count(*) FROM proj_signed_spec").fetchone()[0] == 0
    with pytest.raises(ParityError):
        check_projection_rebuild_parity(conn, _registry())
