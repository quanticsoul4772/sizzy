"""Invariant audit (updated at B2.1): a named test for each of the 18 spec invariants.

Real after B5.5: ALL 18 invariants (1–18). Inv 11/12/17 graduated across B5.2/B5.3/B5.5 — the learning
spine is complete. No partials, no skips: the audit is 18 real / 0 partial / 0 skip (full graduation).
"""

import re
import sqlite3
import sys
from pathlib import Path

import msgspec
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

from devharness import boot
from devharness.events import registry as ev
from devharness.events.bus import EventBus, IntegrityError, verify_chain
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.parity import check_projection_rebuild_parity
from devharness.projections.registry import ProjectionRegistry


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    return conn


# --- Invariants with a B0 substrate implementation: real tests ---------------


def test_inv07_event_log_append_only_hash_chained():
    """Inv 7: append-only, hash-chained; manual mutation fails the integrity check."""
    conn = _db()
    bus = EventBus(conn)
    for i in range(3):
        bus.emit_sync("gate_fired", {"n": i}, correlation_id="corr-1")
    assert verify_chain(conn) == 3
    conn.execute("UPDATE events SET payload='{\"n\":99}' WHERE seq=2")
    conn.commit()
    with pytest.raises(IntegrityError):
        verify_chain(conn)


def test_inv08_projection_rebuild_parity():
    """Inv 8: a from-scratch replay reproduces incremental projection state."""
    conn = _db()
    reg = ProjectionRegistry()
    register_handlers(reg)
    bus = EventBus(conn, reg)
    bus.emit_sync(
        "role_transitioned",
        msgspec.to_builtins(ev.RoleTransitioned(from_role="a", to_role="b")),
        correlation_id="corr-1",
    )
    assert check_projection_rebuild_parity(conn, reg) is True


def test_inv09_correlation_coverage():
    """Inv 9: every event carries a correlation_id; the writer refuses one without."""
    conn = _db()
    bus = EventBus(conn)
    bus.emit_sync("gate_fired", {}, correlation_id="corr-1")
    assert all(row[0] for row in conn.execute("SELECT correlation_id FROM events"))
    with pytest.raises(ValueError):
        bus.emit_sync("gate_fired", {}, correlation_id="")


def test_inv15_required_gates_boot_check(monkeypatch):
    """Inv 15: boot fails closed if any REQUIRED_GATE is unregistered."""
    assert boot.check_required_gates_registered() is True
    monkeypatch.setitem(boot.REQUIRED_GATES, "check_missing_gate", "C1")
    with pytest.raises(boot.BootError):
        boot.check_required_gates_registered()


def _parse_constitution_claims(text: str) -> set[str]:
    names: set[str] = set()
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "Boot-check claim set:":
            in_block = True
            continue
        if in_block:
            match = re.match(r"^- `([a-z0-9_]+)`$", stripped)
            if match:
                names.add(match.group(1))
            else:
                in_block = False
    return names


def test_inv18_constitution_enforcement_parity():
    """Inv 18: the runtime registry equals the constitution claim set (1:N, both ways)."""
    text = (ROOT / ".specify" / "memory" / "constitution.md").read_text(encoding="utf-8")
    constitution = _parse_constitution_claims(text)
    registered = boot.registered_check_names()
    assert constitution == registered  # no unmapped name, no orphan check
    assert len(constitution) == len(boot.REQUIRED_GATES)  # derived: no magic number to bump on a claim change


# --- Invariants whose subsystem is not built until a later cut line -----------

def test_inv01_single_writer_lock():
    """Inv 1 (B2.0): a second concurrent acquire fails closed; one holder at a time."""
    from devharness.events.bus import EventBus
    from devharness.lock.base import LockHeldByAnotherRole, SingleWriterLock
    from devharness.projections.handlers import register_handlers
    from devharness.projections.registry import ProjectionRegistry

    conn = _db()
    reg = ProjectionRegistry()
    register_handlers(reg)
    bus = EventBus(conn, reg)
    lock = SingleWriterLock()
    lock.acquire("developer", "c1", bus, conn)
    with pytest.raises(LockHeldByAnotherRole):
        lock.acquire("reviewer", "c2", bus, conn)
    assert conn.execute("SELECT count(*) FROM proj_lock").fetchone()[0] == 1


def test_inv02_reviewer_no_write_tools():
    """Inv 2 (B2.5): the reviewer's tool inventory has zero write-capable tools."""
    from devharness.call_class import classify
    from devharness.roles.reviewer import reviewer_tool_inventory

    inv = reviewer_tool_inventory()
    assert all(classify(tool) != "mutation" for tool in inv)
    assert not any(t in inv for t in ("Edit", "Write", "Bash", "NotebookEdit"))
    assert not any("write_file" in t or "append_to_file" in t or "run_command" in t for t in inv)


def test_inv03_director_no_file_tools():
    """Inv 3 (B1.4; B2.7 dispatch): the director's tool inventory has zero write tools,
    and dispatch (its only path to code) goes through the developer subprocess — it is
    not a file-write tool. Full dispatch-cost coverage: test_invariant_3_under_dispatch.py."""
    from devharness.call_class import classify
    from devharness.roles.director import DirectorRole, tool_inventory_for

    inv = tool_inventory_for(DirectorRole.ALLOWED_MCP_SERVERS)
    assert all(classify(tool) != "mutation" for tool in inv)
    assert not any(t in inv for t in ("Edit", "Write", "Bash", "NotebookEdit"))
    # B2.7: the director gains dispatch, but dispatch is not a write tool — it spawns
    # the developer; the director's own inventory is unchanged (no ACI write actions).
    assert callable(getattr(DirectorRole, "dispatch", None))
    assert not any("write_file" in t or "run_command" in t for t in inv)


def test_inv04_spec_gate():
    """Inv 4 (B1.3): BUILD is denied without a signed spec and allowed with one."""
    from devharness.gates.base import GateDeny, GateOk
    from devharness.gates.spec_signed import SpecSignedGate

    conn = _db()
    gate = SpecSignedGate()
    ctx = {"conn": conn, "correlation_id": "c"}
    assert isinstance(gate.check(ctx), GateDeny)
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES ('a', 'spec', 1, '{}', 'c', 1, 1)"
    )
    conn.commit()
    assert isinstance(gate.check(ctx), GateOk)


def test_inv05_done_is_earned():
    """Inv 5 (B2.6): completed requires a verifier pass AND a reviewer certification."""
    from devharness.events.bus import EventBus
    from devharness.task_lifecycle.base import TaskLifecycle
    from devharness.task_lifecycle.done_is_earned import DoneNotEarned, complete

    conn = _db()
    bus = EventBus(conn)
    lifecycle = TaskLifecycle()
    lifecycle.transition("t1", "queued", "running", bus, conn)
    with pytest.raises(DoneNotEarned):
        complete("t1", lifecycle, conn, bus)  # neither a verifier pass nor a cert yet
    bus.emit_sync("verifier_outcome", {"task_id": "t1", "verifier": "test_suite", "passed": True, "detail": "", "evidence": {}}, correlation_id="c")
    with pytest.raises(DoneNotEarned):
        complete("t1", lifecycle, conn, bus)  # still missing the reviewer cert
    bus.emit_sync("reviewer_certified", {"task_id": "t1", "reviewer_session_id": "s", "evidence": {}, "correlation_id": "c", "certified_at_millis": 1}, correlation_id="c")
    complete("t1", lifecycle, conn, bus)  # both present -> allowed
    assert lifecycle.state("t1") == "completed"


def test_inv06_handoffs_schema_validated():
    """Inv 6 (B1.1/B1.5): handoff artifacts are validated before consumption."""
    import devharness.artifacts.spec  # noqa: F401  (registers "spec")
    from devharness.artifacts.registry import HandoffValidationError, validate_before_consumption

    valid = {
        "problem": "p", "scope": "s", "non_goals": [], "interfaces": [], "success_criteria": ["sc"],
        "verification_plan": "v", "assumptions": [{"text": "a", "confidence": 0.5, "low_confidence_flag": False}],
        "correlation_id": "c",
    }
    assert validate_before_consumption("spec", valid).problem == "p"
    with pytest.raises(HandoffValidationError):
        validate_before_consumption("spec", {k: v for k, v in valid.items() if k != "problem"})


def test_inv10_no_silent_termination():
    """Inv 10 (B2.6): a running task emits exactly one terminal; a second raises."""
    from devharness.events.bus import EventBus
    from devharness.task_lifecycle.base import TaskLifecycle, TaskLifecycleViolation
    from devharness.task_lifecycle.done_is_earned import abort

    conn = _db()
    bus = EventBus(conn)
    lifecycle = TaskLifecycle()
    lifecycle.transition("t1", "queued", "running", bus, conn)
    abort("t1", "manual", lifecycle, conn, bus)
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='terminal_outcome'").fetchone()[0] == 1
    with pytest.raises(TaskLifecycleViolation):
        abort("t1", "again", lifecycle, conn, bus)  # second terminal transition


def test_inv11_antibodies_text_only():
    """Inv 11 (B5.2): antibodies are text only — no executable-code field on the antibody structs, the
    library CHECK rejects empty pattern_text, and a code-bearing candidate cannot be approved as an
    antibody."""
    from devharness import boot
    assert boot.check_inv_11_antibodies_text_only() is True


def test_inv12_core_gates_unweakable():
    """Inv 12 (B5.3): core gates are unweakable by retro — a core-gate-weakening CANDIDATE is
    auto-rejected at the validator before operator review; tightening is allowed; non-core changes
    pass through."""
    from devharness import boot
    assert boot.check_inv_12_core_gates_unweakable() is True


def test_inv13_cost_mode_confined():
    """Inv 13 (B2.1): `cost_mode ==` comparisons appear only in cost_mode.py and
    cost_router.py (AST scan over runtime/devharness/)."""
    import ast

    devharness = ROOT / "runtime" / "devharness"
    whitelist = {"cost_mode.py", "cost_router.py"}

    def refs_cost_mode(node):
        return (isinstance(node, ast.Name) and node.id == "cost_mode") or (
            isinstance(node, ast.Attribute) and node.attr == "cost_mode"
        )

    offenders = set()
    for py in devharness.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Compare) and any(isinstance(op, ast.Eq) for op in node.ops):
                if any(refs_cost_mode(o) for o in (node.left, *node.comparators)):
                    offenders.add(py.name)
    assert offenders and offenders <= whitelist


def test_inv14_calibration_alignment():
    """Inv 14 (B2.8 FULL): CALL_CLASSES is the single source of truth AND the Brier
    calibration metric's mutation filter derives from the same constant."""
    from devharness.calibration.brier import _is_mutation, compute_brier, compute_brier_for_role
    from devharness.call_class import CALL_CLASSES, classify

    # source-of-truth (B1.0 partial, retained)
    assert CALL_CLASSES == frozenset({"mutation", "read", "harness"})
    assert classify("Write") == "mutation" and classify("Read") == "read"
    for tool in ("Write", "Read", "Task", "unknown-tool"):
        assert classify(tool) in CALL_CLASSES

    # the Brier-metric mutation filter and the role's call_class enumeration both go through
    # classify() -> CALL_CLASSES; divergence would flip these
    assert _is_mutation("write_file") is True  # classify(mcp__devharness-aci__write_file) == "mutation"
    assert _is_mutation("open_file") is False  # read

    # the metric computes a finite value over a representative sample
    brier = compute_brier([(0.9, True), (0.1, False), (0.8, True), (0.2, False)])
    assert 0.0 <= brier <= 1.0

    # and aggregates over the mutation-write event log
    conn = _db()
    bus = EventBus(conn)
    for i in range(3):
        bus.emit_sync("write_attempted", {"task_id": "t1", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "attempted_at_millis": i, "predicted_success": 0.9, "task_class": "new_project_scaffold"}, correlation_id="c")
        bus.emit_sync("write_applied", {"task_id": "t1", "worktree_path": "/w", "target_path": f"f{i}.py", "action_kind": "write_file", "correlation_id": "c", "applied_at_millis": i, "observed_success": True, "task_class": "new_project_scaffold"}, correlation_id="c")
    value = compute_brier_for_role("developer", "new_project_scaffold", conn, min_samples=1)
    assert value is not None and 0.0 <= value <= 1.0


def test_inv16_director_budget_tier():
    """Inv 16 (B1.4): the class sets the tier floor; the router preserves it and the
    director binds it. Full budget-exceeded + tier-violation behavior: test_invariant_16.py."""
    from devharness.roles.director import DirectorRole
    from devharness.roles.iteration_router import TIER_ORDER, select_path
    from devharness.task_classes.base import TaskClassSpec
    from devharness.task_classes.registry import clear_task_classes, register_task_class

    clear_task_classes()
    register_task_class(TaskClassSpec(name="t", reasoning_budget_tokens=1000, tier_minimum="T3", dominant_gate_sensitivity="r"))
    budget, tier, depth = select_path("t", 0.5)
    assert tier == "T3"  # class floor preserved by the router
    assert TIER_ORDER["T1"] < TIER_ORDER["T3"]  # a below-floor request is detectable
    assert callable(DirectorRole.iteration_rate_stakes_router)
    clear_task_classes()


def test_inv17_trusted_memory_verified():
    """Inv 17 (B5.5): cross-project memory is verified before trusted — an imported entry is untrusted
    until a verification event naming the verifier promotes it; locally-created entries start trusted."""
    from devharness import boot
    assert boot.check_inv_17_verified_before_trusted() is True
