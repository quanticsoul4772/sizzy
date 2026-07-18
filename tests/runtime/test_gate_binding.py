"""B3.1: per-class gate profiles + DirectorRole.dispatch consults them in order."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.artifacts.plan import PlannedTask
from devharness.events.bus import EventBus
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.roles.director import DirectorRole
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_classes.gate_binding import required_gates_for, run_admission_gates
from devharness.verifier.base import Verifier, VerifierFailed
from devharness.verifier.registry import FALSIFIERS, register_verifier


class _OkVerifier(Verifier):
    name = "_b31_ok"

    async def verify(self, context):
        return VerifierFailed(name=self.name, reason="unused")


def _ensure_verifier():
    register_builtin_task_classes()
    if "_b31_ok" not in FALSIFIERS:
        register_verifier("_b31_ok", _OkVerifier())


def test_profiles_list_correct_gates():
    assert required_gates_for("feature") == ["scope_gate", "blast_radius_gate", "destructive_command_gate", "verifier_attached_gate"]
    assert required_gates_for("bugfix") == ["scope_gate", "destructive_command_gate", "verifier_attached_gate"]
    assert required_gates_for("refactor") == ["scope_gate", "blast_radius_gate", "destructive_command_gate", "verifier_attached_gate"]
    assert required_gates_for("dependency_bump") == ["blast_radius_gate", "destructive_command_gate", "verifier_attached_gate"]
    assert required_gates_for("new_project_scaffold") == []  # no profile -> no admission gates


def test_run_admission_gates_in_order_and_emits():
    _ensure_verifier()
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)
    task = PlannedTask(task_id="t1", task_class="feature", description="d", scope_boundary=["src/**"], dependencies=[], correlation_id="c", verifier_ref="_b31_ok")
    context = {"planned_task": task, "task_id": "t1", "scope_boundary": ["src/**"], "touched_paths": [], "command_string": "", "task_class": "feature", "correlation_id": "c", "conn": conn}
    results = run_admission_gates("feature", context, bus)

    assert [name for name, _ in results] == required_gates_for("feature")
    fired = [json.loads(p[0])["gate"] for p in conn.execute("SELECT payload FROM events WHERE event_type='gate_fired' ORDER BY seq")]
    assert fired == required_gates_for("feature")  # gate_fired emitted in profile order


class _FakeDeveloper:
    @classmethod
    def spawn(cls, *, conn, correlation_id, event_bus, **kwargs):
        return cls(conn, event_bus)

    def __init__(self, conn, event_bus):
        self.conn = conn
        self.event_bus = event_bus
        self.checkpoint = None

    async def run(self, planned_task, correlation_id):
        self.event_bus.emit_sync("task_started", {"task_id": planned_task.task_id, "role": "developer", "worktree_path": "/w", "correlation_id": correlation_id, "started_at_millis": 99}, correlation_id=correlation_id)


async def _complete(planned_task, developer, conn, event_bus):
    event_bus.emit_sync("terminal_outcome", {"task_id": planned_task.task_id, "outcome": "completed", "detail": "", "reason": "", "correlation_id": planned_task.correlation_id, "terminated_at_millis": 100}, correlation_id=planned_task.correlation_id)


class _R:
    total_cost_usd = 0.0
    result = "ok"
    usage = {"input_tokens": 1, "output_tokens": 1}
    is_error = False


def _reasoning():
    async def query(*, prompt, options):
        yield _R()
    return MCPReasoningClient(query_fn=query)


def test_dispatch_consults_profile_in_order():
    _ensure_verifier()
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    bus.emit_sync("plan_drafted", {"plan_id": "p1", "spec_id": "s", "task_count": 1}, correlation_id="c")
    director = DirectorRole.spawn(conn=conn, correlation_id="c", reasoning=_reasoning(), event_bus=bus, now_millis=lambda: 1)
    task = PlannedTask(task_id="t1", task_class="feature", description="d", scope_boundary=["src/**"], dependencies=[], correlation_id="c", verifier_ref="_b31_ok")

    terminal = asyncio.run(director.dispatch(task, _FakeDeveloper, conn, bus, plan_id="p1", complete_task=_complete))

    assert terminal.outcome == "completed"  # admission passed, developer ran
    rows = list(conn.execute("SELECT event_type, payload FROM events WHERE event_type IN ('gate_fired','task_started') ORDER BY seq"))
    gate_order = [json.loads(p)["gate"] for et, p in rows if et == "gate_fired"]
    assert gate_order == required_gates_for("feature")
    # all admission gates fired before the developer started (took the lock)
    first_started = next(i for i, (et, _) in enumerate(rows) if et == "task_started")
    assert all(et == "gate_fired" for et, _ in rows[:first_started])
