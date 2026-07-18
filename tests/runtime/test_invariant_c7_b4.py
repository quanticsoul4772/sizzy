"""B4.7: C7 re-enforced at 28 tiles — spec §S9 manifest == dashboard registry."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot


def test_c7_passes_at_28():
    assert boot.check_dashboard_tile_coverage() is True


def test_c7_fails_closed_on_b4_mismatch(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("**Tile manifest (C7).** tiles:\n- `oss_intake`\n- `oss_enforcement`\n- `oss_branch`\n\nend\n", encoding="utf-8")
    registry = tmp_path / "registry.js"
    registry.write_text("export const TILE_MANIFEST = ['oss_intake', 'oss_enforcement'];\n", encoding="utf-8")  # missing oss_branch
    with pytest.raises(boot.BootError):
        boot.check_dashboard_tile_coverage(spec_path=spec, registry_path=registry)


def test_c7_matched_b4_synthetic_passes(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("**Tile manifest (C7).** tiles:\n- `oss_intake`\n- `oss_enforcement`\n- `oss_branch`\n\nend\n", encoding="utf-8")
    registry = tmp_path / "registry.js"
    registry.write_text("export const TILE_MANIFEST = ['oss_intake', 'oss_enforcement', 'oss_branch'];\n", encoding="utf-8")
    assert boot.check_dashboard_tile_coverage(spec_path=spec, registry_path=registry) is True
