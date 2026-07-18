"""B2.1: ScopeGate allows within-scope, denies outside-scope."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.gates.base import GateDeny, GateOk, evaluate
from devharness.gates.scope import ScopeGate
from devharness.migrate import migrate


def test_allows_within_scope():
    ctx = {"scope_boundary": ["src/**"], "touched_paths": ["src/main.py", "src/pkg/util.py"], "task_id": "t1"}
    assert isinstance(ScopeGate().check(ctx), GateOk)


def test_denies_outside_scope_with_envelope():
    ctx = {"scope_boundary": ["src/**"], "touched_paths": ["src/main.py", "tests/test_x.py"], "task_id": "t1"}
    deny = ScopeGate().check(ctx)
    assert isinstance(deny, GateDeny)
    assert deny.reason == "File path tests/test_x.py outside declared scope_boundary for task t1"
    assert deny.purpose == "Scope invariant: tasks touch only files declared in their scope_boundary"
    assert deny.fix == "Update the task's scope_boundary to include the path, or work within the existing boundary"


def test_no_touched_paths_passes():
    assert isinstance(ScopeGate().check({"scope_boundary": ["src/**"]}), GateOk)


def test_evaluate_emits_gate_fired():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    ctx = {"conn": conn, "correlation_id": "c", "scope_boundary": ["src/**"], "touched_paths": ["x.py"], "task_id": "t1"}
    evaluate(ScopeGate(), ctx, bus)
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='gate_fired'").fetchone()[0])
    assert payload["gate"] == "scope_gate" and payload["decision"] == "deny"
