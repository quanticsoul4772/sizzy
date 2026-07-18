"""B3.1: explore-pass on a fixture repo -> derived scope_boundary the scope gate enforces."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.explore.runner import run as explore_run
from devharness.explore.scope_derivation import derive_scope_boundary
from devharness.gates.base import GateDeny, GateOk
from devharness.gates.scope import ScopeGate


def _fixture_repo(tmp_path):
    repo = tmp_path / "proj"
    (repo / "src" / "app").mkdir(parents=True)
    (repo / "src" / "app" / "main.py").write_text("def f():\n    return 1\n")
    (repo / "src" / "app" / "tests").mkdir()
    (repo / "src" / "app" / "tests" / "test_main.py").write_text("def test_f():\n    assert True\n")
    (repo / "pyproject.toml").write_text("[project]\nname='proj'\ndependencies=['pytest']\n")
    return repo


def test_derived_scope_accepts_in_scope_denies_out(tmp_path):
    repo = _fixture_repo(tmp_path)
    artifact = explore_run(str(repo), "c")
    scope = derive_scope_boundary(artifact, ["src/app/main.py"])

    gate = ScopeGate()
    # an in-scope write to the target is accepted
    assert isinstance(gate.check({"scope_boundary": scope, "touched_paths": ["src/app/main.py"], "task_id": "t1"}), GateOk)
    # a sibling within the surrounding directory is accepted
    assert isinstance(gate.check({"scope_boundary": scope, "touched_paths": ["src/app/helpers.py"], "task_id": "t1"}), GateOk)
    # an out-of-derived-scope write is denied
    assert isinstance(gate.check({"scope_boundary": scope, "touched_paths": ["secrets/key.txt"], "task_id": "t1"}), GateDeny)


def test_dependency_bump_scope_admits_manifest(tmp_path):
    repo = _fixture_repo(tmp_path)
    artifact = explore_run(str(repo), "c")
    scope = derive_scope_boundary(artifact, ["src/app/main.py"], task_class="dependency_bump")

    gate = ScopeGate()
    assert isinstance(gate.check({"scope_boundary": scope, "touched_paths": ["pyproject.toml"], "task_id": "t1"}), GateOk)
