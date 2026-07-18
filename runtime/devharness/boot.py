"""Boot-check registry and REQUIRED_GATES (B0.5).

``CONSTITUTION_CLAIMS`` mirrors the constitution v0.2.0 claim sets: commitment id
-> boot-check names (23 names total, Invariant 18 1:N map). Every name is
registered — all 23 with real bodies (the original B0.5 stubs graduated across B0–B4;
the v0.2.0 amendment retired the vacuous ``check_role_context_budget_declared``;
the unmapped default now fails closed, and run_boot_checks executes them). ``REQUIRED_GATES``
is every claim name; ``check_required_gates_registered`` asserts each is present
and fails boot closed if any is missing (Invariant 15).
"""

from devharness.projections.parity import check_projection_rebuild_parity


class BootError(RuntimeError):
    """Raised when a required gate is not registered; boot fails closed."""


# Mirror of constitution v0.2.0. Total = 23 names (24 minus the retired per-role-budget claim).
CONSTITUTION_CLAIMS: dict[str, list[str]] = {
    "C1": [
        "check_required_gates_registered",
        "workflow_guard",
        "secret_guard",
        "scope_guard",
        "sandbox",
    ],
    "C2": ["check_terminal_outcome_required_per_task"],
    "C3": ["check_setting_sources_empty"],
    "C4": ["check_handoff_context_assembled_by_harness"],
    "C5": [
        "check_correlation_id_coverage",
        "check_event_log_writer_singleton",
        "check_projection_rebuild_parity",
    ],
    "C6": ["check_director_iteration_router_present"],
    "C7": ["check_dashboard_tile_coverage"],
    "C8": ["check_verifier_attached_gate_registered", "check_verifier_decision_rule_is_code"],
    "C9": ["check_gate_deny_envelope_shape"],
    "C10": ["check_tool_call_required_for_progress"],
    "C11": ["check_single_writer_lock_present", "check_concurrent_write_attempts_fail_closed"],
    "C12": ["check_spec_gate_present", "check_build_state_requires_signed_spec"],
    "C13": [
        "check_handoff_artifact_schema_registered",
        "check_handoff_artifact_validated_before_consumption",
    ],
}


_REGISTRY: dict[str, dict[str, object]] = {}


def register(commitment: str, check_name: str, fn) -> None:
    _REGISTRY.setdefault(commitment, {})[check_name] = fn


def registered_check_names() -> set[str]:
    return {name for checks in _REGISTRY.values() for name in checks}


def _unmapped(*_args, **_kwargs) -> bool:
    """Registration default for a claim name with no real body. Fails CLOSED when called (by
    run_boot_checks) — a boot check must have a real implementation, never silently pass. (All 23
    names currently map to real bodies, so this is only reached if a future claim is left unmapped.)"""
    raise BootError("boot check has no real body (registered to the unmapped default)")


def check_setting_sources_empty() -> bool:
    """Commitment 3: agent sessions never inherit filesystem settings — ``setting_sources=[]``. Fail closed.

    Asserts the LIVE inline posture (the per-role-spec registry was retired in the v0.2.0 amendment): the
    abstract role base (``AgentRole.setting_sources``) and the MCP client every real role drives through
    (``MCPClient.SETTING_SOURCES``) must both be empty. A non-empty default on either is a commitment-3
    regression (settings would bleed into a worker session). Graduated in B1.0.
    """
    from devharness.mcp.base import MCPClient
    from devharness.roles.base import AgentRole

    offenders = []
    if list(AgentRole.setting_sources) != []:
        offenders.append("AgentRole.setting_sources")
    if list(MCPClient.SETTING_SOURCES) != []:
        offenders.append("MCPClient.SETTING_SOURCES")
    if offenders:
        raise BootError(f"commitment 3 violated — non-empty setting_sources: {sorted(offenders)}")
    return True


def check_handoff_artifact_schema_registered() -> bool:
    """C13: the spec handoff schema is registered at startup. Fail closed.

    Graduated in B1.1 (was a stub).
    """
    from devharness.artifacts.registry import HANDOFF_ARTIFACTS
    from devharness.artifacts.spec import SpecArtifact

    if HANDOFF_ARTIFACTS.get("spec") is not SpecArtifact:
        raise BootError("SpecArtifact is not registered under the 'spec' handoff name")
    return True


def check_handoff_artifact_validated_before_consumption() -> bool:
    """C13: validate_before_consumption refuses an invalid spec payload. Fail closed.

    Graduated in B1.1 (was a stub). Probes both failure modes: a missing required
    field and an empty assumptions list.
    """
    from devharness.artifacts.registry import HandoffValidationError, validate_before_consumption

    one_assumption = [{"text": "a", "confidence": 0.5, "low_confidence_flag": False}]
    missing_required = {
        "scope": "s",
        "non_goals": [],
        "interfaces": [],
        "success_criteria": ["sc"],
        "verification_plan": "v",
        "assumptions": one_assumption,
        "correlation_id": "c",
    }
    empty_assumptions = {**missing_required, "problem": "p", "assumptions": []}

    for bad in (missing_required, empty_assumptions):
        try:
            validate_before_consumption("spec", bad)
        except HandoffValidationError:
            continue
        raise BootError("validate_before_consumption accepted an invalid spec payload")
    return True


def check_handoff_context_assembled_by_harness(roles=None) -> bool:
    """C4: every AgentRole subclass builds its initial context from the harness
    (event log + artifacts), never from model- or operator-supplied raw context.

    Graduated in B1.2. Mechanism: introspect each role's ``spawn`` signature — it
    must take ``conn`` (event-log-derived context) and must NOT accept a raw-context
    parameter; the role must define ``assemble_context``. Fails closed.
    """
    import inspect

    from devharness.roles.base import AgentRole

    if roles is None:
        roles = AgentRole.__subclasses__()
    forbidden = {"raw_context", "model_context", "operator_context", "context"}
    for role in roles:
        name = getattr(role, "__name__", role)
        spawn = getattr(role, "spawn", None)
        if spawn is None:
            raise BootError(f"{name} has no harness spawn")
        params = set(inspect.signature(spawn).parameters)
        if "conn" not in params:
            raise BootError(f"{name}.spawn does not derive context from the event log (no conn)")
        raw = forbidden & params
        if raw:
            raise BootError(f"{name}.spawn accepts model/operator-supplied raw context: {sorted(raw)}")
        if not callable(getattr(role, "assemble_context", None)):
            raise BootError(f"{name} lacks assemble_context")
    return True


def check_tool_call_required_for_progress() -> bool:
    """C10: the role progress metric counts tool calls and ignores text-only output.

    Graduated in B1.2. Mechanism: a simulated run with zero tool calls yields zero
    progress; a run with N tool calls yields N. Fails closed.
    """
    from types import SimpleNamespace

    import claude_agent_sdk as sdk

    from devharness.roles.base import progress_from_messages

    text_only = [
        SimpleNamespace(content=[sdk.TextBlock(text="thinking out loud")]),
        SimpleNamespace(content=[sdk.TextBlock(text="more text, no tool")]),
    ]
    if progress_from_messages(text_only) != 0:
        raise BootError("progress metric counted text-only output")

    n = 3
    with_tools = [
        SimpleNamespace(content=[sdk.ToolUseBlock(id=f"t{i}", name="mcp__parallax__elicit", input={}) for i in range(n)])
    ]
    if progress_from_messages(with_tools) != n:
        raise BootError(f"progress metric did not count {n} tool calls")
    return True


def check_spec_gate_present() -> bool:
    """C12: the SpecSignedGate is registered. Fail closed. Graduated in B1.3."""
    import devharness.gates.spec_signed  # noqa: F401  (registers the gate)
    from devharness.gates.registry import GATES
    from devharness.gates.spec_signed import SpecSignedGate

    if not isinstance(GATES.get("spec_signed_gate"), SpecSignedGate):
        raise BootError("SpecSignedGate is not registered under 'spec_signed_gate'")
    return True


def check_build_state_requires_signed_spec() -> bool:
    """C12: the spec gate denies BUILD without a signed spec and allows it with one.

    Fail closed. Graduated in B1.3.
    """
    import sqlite3

    import devharness.gates.spec_signed  # noqa: F401
    from devharness.gates.base import GateDeny, GateOk
    from devharness.gates.registry import GATES
    from devharness.migrate import migrate

    gate = GATES["spec_signed_gate"]
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    if not isinstance(gate.check({"conn": conn, "correlation_id": "c"}), GateDeny):
        raise BootError("spec gate did not deny BUILD without a signed spec")
    conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES ('a', 'spec', 1, '{}', 'c', 1, 1)"
    )
    conn.commit()
    if not isinstance(gate.check({"conn": conn, "correlation_id": "c"}), GateOk):
        raise BootError("spec gate did not allow BUILD with a signed spec")
    return True


def check_gate_deny_envelope_shape(gates=None) -> bool:
    """C9: every gate's deny carries non-empty reason/purpose/fix. Fail closed.

    Graduated in B1.3. Invokes each gate with a synthetic deny-triggering context.
    """
    import sqlite3

    import devharness.gates.spec_signed  # noqa: F401
    from devharness.gates.base import GateOk
    from devharness.gates.registry import GATES
    from devharness.migrate import migrate

    gates = GATES if gates is None else gates
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    synthetic = {"conn": conn, "correlation_id": "__no_such_correlation__"}
    for name, gate in gates.items():
        result = gate.check(synthetic)
        if isinstance(result, GateOk):
            continue
        reason = getattr(result, "reason", "")
        purpose = getattr(result, "purpose", "")
        fix = getattr(result, "fix", "")
        if not (reason and purpose and fix):
            raise BootError(f"gate {name} produced a deny without a full reason/purpose/fix envelope")
    return True


def check_director_iteration_router_present(role=None) -> bool:
    """C6: the director exposes an iteration_rate_stakes_router with the select_path
    interface (task_class, stakes_signal). Fail closed. Graduated in B1.4.
    """
    import inspect

    if role is None:
        from devharness.roles.director import DirectorRole

        role = DirectorRole
    router = getattr(role, "iteration_rate_stakes_router", None)
    if not callable(router):
        raise BootError(f"{getattr(role, '__name__', role)} has no iteration_rate_stakes_router")
    params = list(inspect.signature(router).parameters)
    if params[:2] != ["task_class", "stakes_signal"]:
        raise BootError("iteration_rate_stakes_router lacks the select_path(task_class, stakes_signal) interface")
    return True


def check_single_writer_lock_present() -> bool:
    """C11: the write-lock gate is registered and the lock primitive is importable.

    Fail closed. Graduated in B2.0.
    """
    import devharness.gates.write_lock  # noqa: F401  (registers the gate)
    from devharness.gates.registry import GATES
    from devharness.gates.write_lock import WriteLockGate
    from devharness.lock.base import SingleWriterLock  # noqa: F401  (must be importable)

    if not isinstance(GATES.get("write_lock_gate"), WriteLockGate):
        raise BootError("WriteLockGate is not registered under 'write_lock_gate'")
    return True


def check_concurrent_write_attempts_fail_closed() -> bool:
    """C11: a second acquire while the lock is held fails closed. Graduated in B2.0."""
    import sqlite3

    from devharness.events.bus import EventBus
    from devharness.lock.base import LockHeldByAnotherRole, SingleWriterLock
    from devharness.migrate import migrate
    from devharness.projections.handlers import register_handlers
    from devharness.projections.registry import ProjectionRegistry

    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)
    lock = SingleWriterLock()
    lock.acquire("developer", "c1", bus, conn)
    try:
        lock.acquire("reviewer", "c2", bus, conn)
    except LockHeldByAnotherRole:
        return True
    raise BootError("a second concurrent acquire did not fail closed")


def check_correlation_id_coverage(conn=None) -> bool:
    """C5: every event in the log carries a non-empty correlation_id. Fail closed.

    Graduated in B2.0 (the EventBus enforces this since B0.2; the check makes it
    explicit). With no conn, builds a fresh log and asserts coverage holds.
    """
    import sqlite3

    from devharness.events.bus import EventBus
    from devharness.migrate import migrate

    if conn is None:
        conn = sqlite3.connect(":memory:")
        migrate(conn)
        EventBus(conn).emit_sync("gate_fired", {}, correlation_id="c")
    missing = conn.execute(
        "SELECT count(*) FROM events WHERE correlation_id IS NULL OR correlation_id = ''"
    ).fetchone()[0]
    if missing:
        raise BootError(f"{missing} event(s) lack a correlation_id")
    return True


def check_event_log_writer_singleton(root=None) -> bool:
    """C5: EventBus.emit_sync is the sole writer to the events table. Fail closed.

    Graduated in B2.0. Static AST scan: no string literal containing INSERT INTO
    events anywhere under runtime/devharness/ except events/bus.py.
    """
    import ast
    import re
    from pathlib import Path

    # Require a real INSERT statement (column list / VALUES / SELECT after the table)
    # so prose mentioning the table — including this check's own error message — is not flagged.
    pattern = re.compile(r"insert\s+into\s+events\s*(\(|values\b|select\b)", re.IGNORECASE)
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    offenders = set()
    for py in root.rglob("*.py"):
        if py.relative_to(root).as_posix() == "events/bus.py":
            continue
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and pattern.search(node.value):
                offenders.add(py.relative_to(root).as_posix())
    if offenders:
        raise BootError(f"direct INSERT INTO events outside events/bus.py: {sorted(offenders)}")
    return True


def check_verifier_attached_gate_registered() -> bool:
    """C8: the verifier-attached gate is registered. Fail closed. Graduated in B2.2."""
    import devharness.gates.verifier_attached  # noqa: F401  (registers the gate)
    from devharness.gates.registry import GATES
    from devharness.gates.verifier_attached import VerifierAttachedGate

    if not isinstance(GATES.get("verifier_attached_gate"), VerifierAttachedGate):
        raise BootError("VerifierAttachedGate is not registered under 'verifier_attached_gate'")
    return True


def check_verifier_decision_rule_is_code(falsifiers=None) -> bool:
    """C8: every registered verifier's decision rule is code (a real verify() method),
    not a config-/model-supplied callable. Fail closed. Graduated in B2.2.
    """
    import inspect

    import devharness.verifier.builtin  # noqa: F401  (registers the built-in falsifiers)
    from devharness.verifier.base import Verifier
    from devharness.verifier.registry import FALSIFIERS

    falsifiers = FALSIFIERS if falsifiers is None else falsifiers
    for name, verifier in falsifiers.items():
        fn = getattr(type(verifier), "verify", None)
        if not inspect.isfunction(fn) or fn.__name__ != "verify":
            raise BootError(f"verifier {name} decision rule is not a code verify() method")
        if fn is Verifier.verify or getattr(fn, "__isabstractmethod__", False):
            raise BootError(f"verifier {name} does not override verify() with a code decision rule")
        for attr in ("decision", "decision_rule", "verdict"):
            if hasattr(verifier, attr):
                raise BootError(f"verifier {name} carries a config-supplied decision attribute {attr!r}")
    return True


def check_dashboard_tile_coverage(spec_path=None, registry_path=None) -> bool:
    """C7: the spec §S9 tile manifest matches the dashboard tile registry. Fail closed.

    Graduated in B2.9. Parses the enumerated tile names from devharness-spec.md's "Tile
    manifest (C7" block and from dashboard/src/tiles/registry.js (TILE_MANIFEST). A tile
    the spec names but the dashboard does not register — or vice versa — fails closed.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec_path = Path(spec_path) if spec_path is not None else root / "devharness-spec.md"
    registry_path = Path(registry_path) if registry_path is not None else root / "dashboard" / "src" / "tiles" / "registry.js"

    spec_text = spec_path.read_text(encoding="utf-8")
    spec_tiles = set()
    in_block = False
    for line in spec_text.splitlines():
        if "Tile manifest (C7" in line:
            in_block = True
            continue
        if in_block:
            match = re.match(r"^- `([a-z0-9_]+)`$", line.strip())
            if match:
                spec_tiles.add(match.group(1))
            elif line.strip() and not line.strip().startswith("- "):
                break

    registry_text = registry_path.read_text(encoding="utf-8")
    registry_tiles = set(re.findall(r"'([a-z0-9_]+)'", registry_text))

    if spec_tiles != registry_tiles:
        raise BootError(
            f"dashboard tile coverage mismatch: spec-only={sorted(spec_tiles - registry_tiles)}, "
            f"dashboard-only={sorted(registry_tiles - spec_tiles)}"
        )
    return True


def check_terminal_outcome_required_per_task(conn=None) -> bool:
    """C2: no silent termination — every started task is terminal or still running.

    Graduated in B2.6. Scans proj_task_lifecycle: a row with started_at_millis set but
    no terminal_at_millis and current_state != 'running' is a silently-terminated task.
    Fails closed. With no conn, builds a fresh (vacuously clean) log.
    """
    import sqlite3

    from devharness.migrate import migrate

    if conn is None:
        conn = sqlite3.connect(":memory:")
        migrate(conn)
    offenders = conn.execute(
        "SELECT task_id FROM proj_task_lifecycle "
        "WHERE started_at_millis IS NOT NULL AND terminal_at_millis IS NULL AND current_state != 'running'"
    ).fetchall()
    if offenders:
        raise BootError(f"silently-terminated tasks (no terminal, not running): {[o[0] for o in offenders]}")
    return True


def _gate_denies_known_bad(gate_name: str, bad_context: dict) -> bool:
    """B4.2: a graduated OSS gate must be registered AND enforce — it denies its known-bad
    rather than returning the B4.0 stub's GateOk. Used by the three C1 graduations below."""
    import devharness.task_classes.gate_binding  # noqa: F401  (imports the gate modules -> registers GATES)
    from devharness.gates.base import GateDeny
    from devharness.gates.registry import GATES

    gate = GATES.get(gate_name)
    if gate is None:
        raise BootError(f"{gate_name} gate is not registered")
    result = gate.check(bad_context)
    if not isinstance(result, GateDeny):
        raise BootError(f"{gate_name} does not enforce (still a stub?): returned {type(result).__name__}")
    return True


def check_workflow_guard_registered() -> bool:
    """C1 (B4.2): workflow_guard is registered with a real, enforcing body."""
    return _gate_denies_known_bad("workflow_guard", {"touched_paths": [".github/workflows/ci.yml"]})


def check_secret_guard_registered() -> bool:
    """C1 (B4.2): secret_guard is registered with a real, enforcing body."""
    return _gate_denies_known_bad("secret_guard", {"diff_content": "+token = ghp_" + "a" * 36})


def check_scope_guard_registered() -> bool:
    """C1 (B4.2): scope_guard is registered with a real, enforcing body."""
    return _gate_denies_known_bad("scope_guard", {"diff_content": "\n".join("+l" for _ in range(501))})


def check_sandbox_registered() -> bool:
    """C1 (B4.3): sandbox is registered with a real, enforcing body — it denies when only the
    fail-closed mock launcher is available (host-independent: forces preferred=mock)."""
    return _gate_denies_known_bad("sandbox", {"sandbox_launcher_preferred": "mock"})


# Real check bodies wired so far. C5 parity (B0.3/B0.4), the two C3 role-posture
# checks (B1.0), the two C13 handoff checks (B1.1), C4 + C10 (B1.2), the two C12
# spec-gate checks + C9 deny-envelope (B1.3), C6 director router (B1.4), the two
# C11 lock checks + the two remaining C5 substrate checks (B2.0), the two C8
# verifier checks (B2.2), C2 terminal-outcome (B2.6), C7 tile coverage (B2.9), and the
# three C1 path/LOC OSS gates (B4.2: workflow_guard/secret_guard/scope_guard) + the C1
# sandbox gate (B4.3) — all four C1 OSS gates now real, all 23 boot-check bodies real. The C1 name
# "check_required_gates_registered" is wired real after its definition below (forward-ref).
_REAL: dict[str, object] = {
    "check_projection_rebuild_parity": check_projection_rebuild_parity,
    "check_setting_sources_empty": check_setting_sources_empty,
    "check_handoff_artifact_schema_registered": check_handoff_artifact_schema_registered,
    "check_handoff_artifact_validated_before_consumption": check_handoff_artifact_validated_before_consumption,
    "check_handoff_context_assembled_by_harness": check_handoff_context_assembled_by_harness,
    "check_tool_call_required_for_progress": check_tool_call_required_for_progress,
    "check_spec_gate_present": check_spec_gate_present,
    "check_build_state_requires_signed_spec": check_build_state_requires_signed_spec,
    "check_gate_deny_envelope_shape": check_gate_deny_envelope_shape,
    "check_director_iteration_router_present": check_director_iteration_router_present,
    "check_single_writer_lock_present": check_single_writer_lock_present,
    "check_concurrent_write_attempts_fail_closed": check_concurrent_write_attempts_fail_closed,
    "check_correlation_id_coverage": check_correlation_id_coverage,
    "check_event_log_writer_singleton": check_event_log_writer_singleton,
    "check_verifier_attached_gate_registered": check_verifier_attached_gate_registered,
    "check_verifier_decision_rule_is_code": check_verifier_decision_rule_is_code,
    "check_terminal_outcome_required_per_task": check_terminal_outcome_required_per_task,
    "check_dashboard_tile_coverage": check_dashboard_tile_coverage,
    # B4.2: three of the four C1 OSS-gate stubs graduate; B4.3: the 4th (sandbox) graduates -> all 24 real
    "workflow_guard": check_workflow_guard_registered,
    "secret_guard": check_secret_guard_registered,
    "scope_guard": check_scope_guard_registered,
    "sandbox": check_sandbox_registered,
}

for _commitment, _names in CONSTITUTION_CLAIMS.items():
    for _name in _names:
        register(_commitment, _name, _REAL.get(_name, _unmapped))


# Every claim name must be registered at boot (Invariant 15 + the Invariant 18 target).
REQUIRED_GATES: dict[str, str] = {
    name: commitment for commitment, names in CONSTITUTION_CLAIMS.items() for name in names
}


def check_required_gates_registered() -> bool:
    """Assert every REQUIRED_GATES name is registered. Fail boot closed on any miss."""
    registered = registered_check_names()
    missing = [name for name in REQUIRED_GATES if name not in registered]
    if missing:
        raise BootError(f"required gates not registered: {sorted(missing)}")
    return True


# Wire the real check_required_gates_registered body into the C1 registry (it is defined after the
# _REAL dict, so it cannot be a forward reference there). Overrides the earlier _ok registration —
# the body has always existed and run; this makes the registry reflect it (B4.2 ledger correction).
register("C1", "check_required_gates_registered", check_required_gates_registered)


def run_boot_checks(conn=None, registry=None) -> bool:
    """Execute EVERY registered boot check, failing closed (BootError) on any failure (#C4).

    This is the actual boot gate — the drivers call it before the first write. Previously nothing
    iterated the registry and CALLED the checks, so "24/24 fail-closed at boot" was an emergent
    property of per-check unit tests, and the (former) `_ok` default would have silently passed an
    unmapped check. Checks are dispatched generically by signature: those with a `conn` / `registry`
    parameter receive the supplied pair (a fresh in-memory migrated db + a handler-registered
    projection registry when not provided); the rest are self-contained.
    """
    import inspect
    import sqlite3

    from devharness.migrate import migrate
    from devharness.projections.handlers import register_handlers
    from devharness.projections.registry import ProjectionRegistry

    if conn is None:
        conn = sqlite3.connect(":memory:")
        migrate(conn)
    if registry is None:
        registry = ProjectionRegistry()
        register_handlers(registry)

    failures: list[tuple[str, str]] = []
    for checks in _REGISTRY.values():
        for name, fn in checks.items():
            params = inspect.signature(fn).parameters
            kwargs = {}
            if "conn" in params:
                kwargs["conn"] = conn
            if "registry" in params:
                kwargs["registry"] = registry
            try:
                result = fn(**kwargs)
            except Exception as exc:  # a failing/raising check is a boot failure, not a crash
                failures.append((name, repr(exc)))
                continue
            if result is not True:
                failures.append((name, f"returned {result!r}"))
    if failures:
        raise BootError(f"boot checks failed ({len(failures)}): {sorted(failures)}")
    return True


# B5.2 — Inv 11 graduation. Not a constitution boot-check name (the 24 are fixed); the invariant audit
# (test_invariants.py) calls this to assert antibodies are text only. Fail closed.
_ANTIBODY_CODE_FIELD_HINTS = ("callable", "code", "code_blob", "eval", "callable_ref", "exec")


def check_inv_11_antibodies_text_only() -> bool:
    """Inv 11: antibodies are text only. Asserts (1) the antibody structs carry no executable-code
    field, (2) proj_antibody_library rejects empty pattern_text, (3) a code-bearing CANDIDATE cannot be
    approved as an antibody (the antibody queue is structurally text-only)."""
    import sqlite3

    from devharness.events.bus import EventBus
    from devharness.events.registry import AntibodyAdded, AntibodyCandidate
    from devharness.migrate import migrate
    from devharness.retro.approval import CandidateNotFound, approve_antibody_candidate

    # (1) no executable-code field on the antibody structs (only str/list/int/Literal/metadata)
    for struct in (AntibodyCandidate, AntibodyAdded):
        for field in struct.__struct_fields__:
            low = field.lower()
            if any(hint in low for hint in _ANTIBODY_CODE_FIELD_HINTS):
                raise BootError(f"Inv 11: {struct.__name__}.{field} looks like an executable-code field")

    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)

    # (2) the library CHECK rejects empty pattern_text
    try:
        conn.execute(
            "INSERT INTO proj_antibody_library (antibody_row_id, pattern_text, source_candidate_id, added_by, added_at_millis, correlation_id) "
            "VALUES (1, '', 'c', 'op', 1, 'c')"
        )
        raise BootError("Inv 11: proj_antibody_library accepted an empty pattern_text")
    except sqlite3.IntegrityError:
        pass

    # (3) a gate-change (code-bearing) candidate cannot be approved as an antibody — it is not in the
    # antibody queue, so the approval pipeline refuses it before any library insert
    conn.execute(
        "INSERT INTO proj_gate_change_queue (gate_change_row_id, retro_run_correlation_id, target_gate, "
        "change_kind, change_details_json, source, created_at_millis) VALUES (99, 'c', 'cost_mode_gate', 'loosen', '{}', 't0', 1)"
    )
    conn.commit()
    try:
        approve_antibody_candidate(99, "op", conn, bus)
        raise BootError("Inv 11: a gate-change candidate was approved as an antibody")
    except CandidateNotFound:
        pass
    return True


def check_inv_12_core_gates_unweakable() -> bool:
    """Inv 12: core gates are unweakable by retro. Asserts the CORE_GATES set is exactly the seven
    enforced gates, the validator blocks weakening (loosen/remove) of any core gate while allowing
    tightening, a synthetic weakening candidate is auto-rejected within one handler-tick + emits
    gate_change_rejected, a non-core candidate stays pending, and the LLM filter shares the same set."""
    from devharness.events.bus import EventBus
    from devharness.migrate import migrate
    from devharness.projections.handlers import register_handlers
    from devharness.projections.registry import ProjectionRegistry
    from devharness.retro import llm_residue
    from devharness.retro.gate_change_validator import CORE_GATES, validate_gate_change_candidate, would_weaken_core_gate

    if CORE_GATES != {"workflow_guard", "secret_guard", "scope_guard", "sandbox",
                      "write_lock_gate", "spec_signed_gate", "verifier_attached_gate"}:
        raise BootError(f"Inv 12: CORE_GATES is not the seven expected gates: {sorted(CORE_GATES)}")

    # the validator's decision logic: every core gate weakens, none tightens; non-core never weakens
    for g in CORE_GATES:
        if not (would_weaken_core_gate(g, "loosen") and would_weaken_core_gate(g, "remove_signature")):
            raise BootError(f"Inv 12: weakening {g} was not blocked")
        if would_weaken_core_gate(g, "tighten") or would_weaken_core_gate(g, "add_signature"):
            raise BootError(f"Inv 12: tightening {g} was wrongly blocked")
    if would_weaken_core_gate("cooldown_gate", "loosen"):
        raise BootError("Inv 12: a non-core gate change was wrongly blocked")

    # the LLM filter and the validator share one CORE_GATES object (single source of truth)
    if llm_residue.CORE_GATES is not CORE_GATES:
        raise BootError("Inv 12: llm_residue.CORE_GATES is not the validator's CORE_GATES (drift)")

    import sqlite3
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)

    # a synthetic core-gate-weakening candidate is auto-rejected by the persistence-path handler
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s",
                  "target_gate": "secret_guard", "change_kind": "loosen", "change_details": {},
                  "evidence_event_ids": [], "source": "llm", "created_at_millis": 1}, correlation_id="c")
    weak_id = conn.execute("SELECT gate_change_row_id FROM proj_gate_change_queue WHERE target_gate='secret_guard'").fetchone()[0]
    if conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE gate_change_row_id=?", (weak_id,)).fetchone()[0] != "rejected":
        raise BootError("Inv 12: a core-gate-weakening candidate was not auto-rejected")
    # the validator emits the gate_change_rejected audit event for it
    validate_gate_change_candidate(weak_id, conn, bus)
    if conn.execute("SELECT count(*) FROM events WHERE event_type='gate_change_rejected'").fetchone()[0] != 1:
        raise BootError("Inv 12: validate did not emit gate_change_rejected")

    # a non-core candidate stays pending for operator review
    bus.emit_sync("gate_change_candidate", {"retro_run_correlation_id": "c", "signature_name": "s",
                  "target_gate": "cost_mode_gate", "change_kind": "loosen", "change_details": {},
                  "evidence_event_ids": [], "source": "t0", "created_at_millis": 1}, correlation_id="c")
    pending = conn.execute("SELECT review_state FROM proj_gate_change_queue WHERE target_gate='cost_mode_gate'").fetchone()[0]
    if pending != "pending":
        raise BootError("Inv 12: a non-core candidate was not left pending")
    return True


def check_inv_17_verified_before_trusted() -> bool:
    """Inv 17: cross-project memory is verified before trusted. Asserts a locally-created entry is
    trusted (verified_locally=1); an imported (foreign-project) entry is untrusted and absent from
    list_verified_memory until verify_memory_entry is called, after which it appears."""
    import sqlite3

    from devharness.events.bus import EventBus
    from devharness.memory.base import project_name
    from devharness.memory.store import create_memory_entry, list_verified_memory, verify_memory_entry
    from devharness.migrate import migrate
    from devharness.projections.handlers import register_handlers
    from devharness.projections.registry import ProjectionRegistry

    conn = sqlite3.connect(":memory:")
    migrate(conn)
    registry = ProjectionRegistry()
    register_handlers(registry)
    bus = EventBus(conn, registry)

    # a locally-created entry is trusted in this project's context
    local_id = create_memory_entry("antibody", {"pattern_text": "local"}, conn, bus, now_millis=lambda: 1)
    if conn.execute("SELECT verified_locally FROM proj_memory WHERE entry_id=?", (local_id,)).fetchone()[0] != 1:
        raise BootError("Inv 17: a locally-created memory entry is not trusted")

    # a synthetic IMPORT from a different project lands untrusted (verified_locally=0)
    foreign = "imported-entry-1"
    assert project_name() != "other-project"
    bus.emit_sync("memory_entry_created", {"entry_id": foreign, "entry_type": "antibody",
                  "entry_payload_json": '{"pattern_text": "imported"}', "source_project": "other-project",
                  "created_at_millis": 2}, correlation_id="memory_import")
    if conn.execute("SELECT verified_locally FROM proj_memory WHERE entry_id=?", (foreign,)).fetchone()[0] != 0:
        raise BootError("Inv 17: an imported memory entry was trusted on arrival")
    if any(e.entry_id == foreign for e in list_verified_memory(conn)):
        raise BootError("Inv 17: an unverified imported entry appeared in the trusted set")

    # verify-before-trusted: only after a verification event (naming the verifier) does it become trusted
    verify_memory_entry(foreign, {"verifier": "feature_spec_claim", "evidence": "re-checked"}, "operator", conn, bus, now_millis=lambda: 3)
    if not any(e.entry_id == foreign for e in list_verified_memory(conn)):
        raise BootError("Inv 17: a verified imported entry did not enter the trusted set")
    row = conn.execute("SELECT verified_locally, verifier_evidence_json FROM proj_memory WHERE entry_id=?", (foreign,)).fetchone()
    if row[0] != 1 or "feature_spec_claim" not in (row[1] or ""):
        raise BootError("Inv 17: a verified entry does not carry its verification evidence")
    return True
