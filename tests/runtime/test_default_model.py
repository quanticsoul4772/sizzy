"""The harness's model assignments resolve through one source of truth (devharness.models).

All four LLM-consuming sites (MCPClient — every parallax/mcp-reasoning/synthesis call — the
developer's code-writing worker, the scope resolver, and discovery) previously hardcoded the prior
frontier model at their signatures. They now resolve `model or default_model()`: an explicit kwarg
wins, then the DEVHARNESS_MODEL env override, then the built-in frontier default.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.mcp.base import MCPClient
from devharness.models import default_model, model_for_tier
from devharness.roles.developer import DeveloperRole
from devharness.roles.discovery import DiscoveryRole


def test_default_model_built_in():
    assert default_model() == "claude-fable-5"


def test_tier_router_maps_advisory_cheaper_writer_frontier():
    # rev 0.3.82: the tier->model router. T2/T3 (writer + quality gate) stay frontier; T0/T1
    # (advisory exploration) run the cheaper model. Unknown tier fails safe to frontier.
    assert model_for_tier("T3") == "claude-fable-5"
    assert model_for_tier("T2") == "claude-fable-5"
    assert model_for_tier("T1") == "claude-sonnet-5"
    assert model_for_tier("T0") == "claude-sonnet-5"
    assert model_for_tier("nonsense") == "claude-fable-5"  # never silently downgrade an unknown tier


def test_devharness_model_pins_every_tier(monkeypatch):
    # a whole-process pin overrides the ladder — all tiers resolve to it
    monkeypatch.setenv("DEVHARNESS_MODEL", "claude-opus-4-8")
    for tier in ("T0", "T1", "T2", "T3"):
        assert model_for_tier(tier) == "claude-opus-4-8"


def test_advisory_construction_routes_to_t1(monkeypatch):
    # the router's real effect: advisory clients carry the cheaper model while a writer-tier client
    # carries frontier — inspected via the MCPClient the construction sites build.
    assert _mcp_client(model=model_for_tier("T1")).model == "claude-sonnet-5"
    assert _mcp_client(model=model_for_tier("T2")).model == "claude-fable-5"
    assert DiscoveryRole(event_bus=None, conn=None, target_repo=".", correlation_id="c",
                         model=model_for_tier("T1")).model == "claude-sonnet-5"


def test_build_class_writer_tiers_route_correctly():
    # rev 0.3.84: bugfix + dependency_bump writers run cheaper (their class tier is T1); the other
    # BUILD classes' writers stay frontier (T2). The router turns the class tier into the writer model.
    # register the builtins this test reads — self-sufficient regardless of xdist worker order
    # (test_task_class_registry's teardown clears the module-global registry, and builtin.py only
    # registers on first import; idempotent, so a re-register is safe).
    from devharness.task_classes.builtin import register_builtin_task_classes
    from devharness.task_classes.registry import TASK_CLASSES
    register_builtin_task_classes()

    assert model_for_tier(TASK_CLASSES["bugfix"].tier_minimum) == "claude-sonnet-5"
    assert model_for_tier(TASK_CLASSES["dependency_bump"].tier_minimum) == "claude-sonnet-5"
    for cls in ("new_project_scaffold", "feature", "refactor"):
        assert model_for_tier(TASK_CLASSES[cls].tier_minimum) == "claude-fable-5"


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_MODEL", "claude-sonnet-5")
    assert default_model() == "claude-sonnet-5"


def _mcp_client(**kwargs):
    return MCPClient(server_name="s", tools=["t"], mcp_servers={"s": {}}, **kwargs)


def test_mcp_client_resolves_the_shared_default(monkeypatch):
    assert _mcp_client().model == "claude-fable-5"
    monkeypatch.setenv("DEVHARNESS_MODEL", "claude-sonnet-5")
    assert _mcp_client().model == "claude-sonnet-5"  # late-bound: env read at construction
    assert _mcp_client(model="explicit-x").model == "explicit-x"  # explicit kwarg still wins


def test_developer_role_resolves_the_shared_default(monkeypatch):
    role = DeveloperRole(event_bus=None, conn=None, context={})
    assert role.model == "claude-fable-5"
    monkeypatch.setenv("DEVHARNESS_MODEL", "claude-sonnet-5")
    assert DeveloperRole(event_bus=None, conn=None, context={}).model == "claude-sonnet-5"
    assert DeveloperRole(event_bus=None, conn=None, context={}, model="explicit-x").model == "explicit-x"


def test_discovery_role_resolves_the_shared_default(monkeypatch):
    kwargs = dict(event_bus=None, conn=None, target_repo=".", correlation_id="c")
    assert DiscoveryRole(**kwargs).model == "claude-fable-5"
    monkeypatch.setenv("DEVHARNESS_MODEL", "claude-sonnet-5")
    assert DiscoveryRole(**kwargs).model == "claude-sonnet-5"
    assert DiscoveryRole(**kwargs, model="explicit-x").model == "explicit-x"


def test_no_hardcoded_model_ids_outside_models_py():
    # the single-source-of-truth guard: no runtime module besides devharness/models.py names a
    # concrete claude-* model id (tests and generated files are out of scope by construction).
    runtime_root = Path(__file__).resolve().parents[2] / "runtime" / "devharness"
    offenders = []
    for py in runtime_root.rglob("*.py"):
        if py.name == "models.py":
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        if "claude-opus" in text or "claude-fable" in text or "claude-sonnet" in text or "claude-haiku" in text:
            offenders.append(str(py.relative_to(runtime_root)))
    assert offenders == []
