"""B2.9: C7 — dashboard tile coverage (spec §S9 manifest == dashboard registry)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot


def test_registered_under_c7():
    assert "check_dashboard_tile_coverage" in boot.registered_check_names()
    assert boot.REQUIRED_GATES["check_dashboard_tile_coverage"] == "C7"


def test_spec_and_registry_match():
    assert boot.check_dashboard_tile_coverage() is True


def test_fails_closed_on_mismatch(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text(
        "intro\n\n**Tile manifest (C7).** these tiles:\n- `alpha`\n- `beta`\n- `gamma`\n\nnext section\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.js"
    registry.write_text("export const TILE_MANIFEST = ['alpha', 'beta'];\n", encoding="utf-8")  # missing gamma
    with pytest.raises(boot.BootError):
        boot.check_dashboard_tile_coverage(spec_path=spec, registry_path=registry)


def test_passes_on_synthetic_match(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("**Tile manifest (C7).** x:\n- `alpha`\n- `beta`\n\nend\n", encoding="utf-8")
    registry = tmp_path / "registry.js"
    registry.write_text("export const TILE_MANIFEST = ['alpha', 'beta'];\n", encoding="utf-8")
    assert boot.check_dashboard_tile_coverage(spec_path=spec, registry_path=registry) is True
