"""#M7: the antibody_screen gate applies learned antibodies to a realized diff (they were never applied).

match_against_text had no caller — antibodies were learned + operator-approved but screened nothing.
The gate now denies a diff that contains an active antibody's pattern, passes a clean diff, ignores a
revoked antibody, and passes when there's no library/conn (the synthetic boot-check context).
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.gates.antibody_screen import AntibodyScreenGate
from devharness.gates.base import GateDeny, GateOk
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.retro.antibody_library import add_antibody, revoke_antibody

_GATE = AntibodyScreenGate()


def _conn():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    return conn, EventBus(conn, registry)


def test_matching_diff_is_denied():
    conn, bus = _conn()
    add_antibody("os.system(", "cand-1", "operator", conn, bus, now_millis=lambda: 1)
    result = _GATE.check({"conn": conn, "diff_content": "+    os.system('rm -rf /')\n"})
    assert isinstance(result, GateDeny)
    assert "os.system(" in result.reason


def test_clean_diff_passes():
    conn, bus = _conn()
    add_antibody("os.system(", "cand-1", "operator", conn, bus, now_millis=lambda: 1)
    assert isinstance(_GATE.check({"conn": conn, "diff_content": "+    x = 1\n"}), GateOk)


def test_revoked_antibody_does_not_match():
    conn, bus = _conn()
    row = add_antibody("os.system(", "cand-1", "operator", conn, bus, now_millis=lambda: 1)
    revoke_antibody(row, "stale pattern", "operator", conn, bus, now_millis=lambda: 2)
    assert isinstance(_GATE.check({"conn": conn, "diff_content": "os.system('x')"}), GateOk)


def test_no_conn_passes():
    assert isinstance(_GATE.check({"diff_content": "os.system("}), GateOk)


def test_screen_text_field_is_also_screened():
    conn, bus = _conn()
    add_antibody("DROP TABLE", "c", "operator", conn, bus, now_millis=lambda: 1)
    assert isinstance(_GATE.check({"conn": conn, "screen_text": "... DROP TABLE users ..."}), GateDeny)


def test_removed_line_with_pattern_is_not_denied():
    # deleting a known-bad pattern must NOT be denied — the diff's '-' line still contains it (review #1)
    conn, bus = _conn()
    add_antibody("os.system(", "c", "operator", conn, bus, now_millis=lambda: 1)
    diff = "@@ -1 +1 @@\n-    os.system('old')\n+    safe_call()\n"
    assert isinstance(_GATE.check({"conn": conn, "diff_content": diff}), GateOk)


def test_context_line_with_pattern_is_not_denied():
    # a pattern on an unchanged context line (leading space) is not introduced by this change (review #1)
    conn, bus = _conn()
    add_antibody("os.system(", "c", "operator", conn, bus, now_millis=lambda: 1)
    diff = "@@ -1,2 +1,2 @@\n     os.system('existing')\n+    added_clean()\n"
    assert isinstance(_GATE.check({"conn": conn, "diff_content": diff}), GateOk)


def test_added_line_with_pattern_is_still_denied():
    conn, bus = _conn()
    add_antibody("os.system(", "c", "operator", conn, bus, now_millis=lambda: 1)
    diff = "@@ -1 +1,2 @@\n context\n+    os.system('new')\n"
    assert isinstance(_GATE.check({"conn": conn, "diff_content": diff}), GateDeny)


def test_short_pattern_below_floor_is_ignored():
    conn, bus = _conn()
    add_antibody("os", "c", "operator", conn, bus, now_millis=lambda: 1)  # 2 chars < floor -> not screened
    assert isinstance(_GATE.check({"conn": conn, "diff_content": "+import os\n"}), GateOk)
