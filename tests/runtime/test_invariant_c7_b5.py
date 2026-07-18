"""C7: spec §S9 manifest == dashboard registry (27 tiles: 25 after rev 0.3.31 + resource_health 0.3.32 + cost 0.3.81)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot

_FOUR = "- `candidate_queue`\n- `antibody_library`\n- `retro_activity`\n- `trusted_memory`\n"


def test_c7_passes_at_27():
    assert boot.check_dashboard_tile_coverage() is True


def test_c7_fails_closed_on_b5_mismatch(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text(f"**Tile manifest (C7).** tiles:\n{_FOUR}\nend\n", encoding="utf-8")
    registry = tmp_path / "registry.js"
    # missing trusted_memory
    registry.write_text("export const TILE_MANIFEST = ['candidate_queue', 'antibody_library', 'retro_activity'];\n", encoding="utf-8")
    with pytest.raises(boot.BootError):
        boot.check_dashboard_tile_coverage(spec_path=spec, registry_path=registry)


def test_c7_matched_b5_synthetic_passes(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text(f"**Tile manifest (C7).** tiles:\n{_FOUR}\nend\n", encoding="utf-8")
    registry = tmp_path / "registry.js"
    registry.write_text("export const TILE_MANIFEST = ['candidate_queue', 'antibody_library', 'retro_activity', 'trusted_memory'];\n", encoding="utf-8")
    assert boot.check_dashboard_tile_coverage(spec_path=spec, registry_path=registry) is True
