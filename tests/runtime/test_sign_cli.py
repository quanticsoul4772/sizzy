"""B1.3: `devharness sign` emits spec_signed, sets signed=1, refuses unknown ids."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cli.sign import UnknownSpec, sign_spec
from devharness.events.bus import EventBus
from devharness.migrate import migrate


def _insert_spec(conn, artifact_id, correlation_id):
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, '{}', ?, 1, 0)",
        (artifact_id, correlation_id),
    )
    conn.commit()


def test_sign_emits_event_and_sets_signed(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OPERATOR", "alice")
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    _insert_spec(conn, "spec-1", "corr-1")

    sign_spec(conn, bus, "spec-1")

    assert conn.execute("SELECT signed FROM artifacts WHERE artifact_id='spec-1'").fetchone()[0] == 1
    row = conn.execute("SELECT correlation_id, payload FROM events WHERE event_type='spec_signed'").fetchone()
    assert row[0] == "corr-1"
    payload = json.loads(row[1])
    assert payload["spec_id"] == "spec-1"
    assert payload["signer"] == "alice"


def test_sign_refuses_unknown_spec():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    with pytest.raises(UnknownSpec):
        sign_spec(conn, EventBus(conn), "nope")


def test_operator_param_overrides_identity():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    _insert_spec(conn, "spec-2", "corr-2")
    sign_spec(conn, bus, "spec-2", operator="bob")
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='spec_signed'").fetchone()[0])
    assert payload["signer"] == "bob"
