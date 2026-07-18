"""B5.4: `devharness retro` CLI — list-pending / approve / reject round-trip; reviewer identity."""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.cli import retro as cli
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry


def _setup():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def _seed(bus):
    bus.emit_sync("antibody_candidate", {"retro_run_correlation_id": "c", "signature_name": "sig_a", "pattern_text": "leak", "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "sig_b", "target_gate": "cost_mode_gate", "change_kind": "loosen", "change_details": {}, "evidence_event_ids": [], "source": "t0", "created_at_millis": 2}, correlation_id="c")


def test_list_pending_both_queues():
    conn, bus = _setup()
    _seed(bus)
    rows = cli.list_pending(conn, queue="all")
    assert {r["queue"] for r in rows} == {"antibody", "gate-change"}
    assert cli.list_pending(conn, queue="antibody")[0]["detail"] == "leak"


def test_reviewer_identity_env_then_os(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_OPERATOR_ID", "alice")
    assert cli.reviewer_identity() == "alice"
    monkeypatch.delenv("DEVHARNESS_OPERATOR_ID", raising=False)
    assert cli.reviewer_identity()  # falls back to the OS user (non-empty)


def test_approve_round_trips(monkeypatch):
    conn, bus = _setup()
    _seed(bus)
    cand = conn.execute("SELECT antibody_row_id FROM proj_antibody_queue").fetchone()[0]
    monkeypatch.setenv("DEVHARNESS_OPERATOR_ID", "alice")
    # drive the API directly with the CLI's helpers (the argparse main wires a fresh DB; the API is the unit)
    from devharness.retro.approval import approve_antibody_candidate
    approve_antibody_candidate(cand, cli.reviewer_identity(), conn, bus)
    assert conn.execute("SELECT review_state, reviewed_by FROM proj_antibody_queue WHERE antibody_row_id=?", (cand,)).fetchone() == ("approved", "alice")


def test_reject_requires_reason_in_argparse():
    # the reject subcommand requires --reason; argparse exits(2) without it
    try:
        cli.main(["reject", "antibody", "1"])
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert exc.code == 2
