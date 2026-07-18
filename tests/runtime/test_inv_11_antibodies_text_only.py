"""B5.2: Inv 11 graduation — antibodies are text only (the boot-check body + its three assertions)."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.events.bus import EventBus
from devharness.events.registry import AntibodyAdded, AntibodyCandidate
from devharness.migrate import migrate
from devharness.retro.approval import CandidateNotFound, approve_antibody_candidate

_CODE_HINTS = ("callable", "code", "code_blob", "eval", "callable_ref", "exec")


def test_inv_11_boot_check_passes():
    assert boot.check_inv_11_antibodies_text_only() is True


def test_antibody_structs_have_no_code_field():
    for struct in (AntibodyCandidate, AntibodyAdded):
        for field in struct.__struct_fields__:
            assert not any(h in field.lower() for h in _CODE_HINTS), f"{struct.__name__}.{field}"


def test_library_check_rejects_empty_pattern_text():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO proj_antibody_library (antibody_row_id, pattern_text, source_candidate_id, added_by, added_at_millis, correlation_id) VALUES (1, '', 'c', 'op', 1, 'c')")


def test_code_bearing_candidate_cannot_be_approved_as_antibody():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    # a gate-change (code-bearing) candidate lives in the gate-change queue, not the antibody queue
    conn.execute("INSERT INTO proj_gate_change_queue (gate_change_row_id, retro_run_correlation_id, target_gate, change_kind, change_details_json, source, created_at_millis) VALUES (7, 'c', 'cost_mode_gate', 'loosen', '{}', 't0', 1)")
    conn.commit()
    with pytest.raises(CandidateNotFound):
        approve_antibody_candidate(7, "op", conn, bus)  # cannot be approved as an antibody
    assert conn.execute("SELECT count(*) FROM proj_antibody_library").fetchone()[0] == 0
