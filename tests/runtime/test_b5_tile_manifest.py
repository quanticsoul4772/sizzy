"""TILE_MANIFEST lists 25 tile names matching the spec §S9 manifest.

(B5.6 brought it to 32; spec rev 0.3.31 removed the 7 feedless B0 generic placeholders —
proj_spec/proj_plan/proj_cost/proj_antibody_queue/proj_gate_change_queue/proj_lock/proj_boot_parity
— that had no event feed and duplicated dedicated named tiles, 32→25. The 4 B5 tiles remain.)"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "dashboard" / "src" / "tiles" / "registry.js"
SPEC = ROOT / "devharness-spec.md"

B5_TILES = {"candidate_queue", "antibody_library", "retro_activity", "trusted_memory"}


def _registry_tiles():
    return set(re.findall(r"'([a-z0-9_]+)'", REGISTRY.read_text(encoding="utf-8")))


def _spec_tiles():
    text = SPEC.read_text(encoding="utf-8")
    tiles, in_block = set(), False
    for line in text.splitlines():
        if "Tile manifest (C7" in line:
            in_block = True
            continue
        if in_block:
            m = re.match(r"^- `([a-z0-9_]+)`$", line.strip())
            if m:
                tiles.add(m.group(1))
            elif line.strip() and not line.strip().startswith("- "):
                break
    return tiles


def test_registry_has_28_tiles():
    tiles = _registry_tiles()
    assert len(tiles) == 28  # 25 (0.3.31) + resource_health (0.3.32) + cost (0.3.81) + invariant_monitor (0.3.87)
    assert B5_TILES <= tiles


def test_spec_manifest_has_28_tiles():
    assert len(_spec_tiles()) == 28
    assert B5_TILES <= _spec_tiles()


def test_registry_matches_spec_manifest():
    assert _registry_tiles() == _spec_tiles()


def test_each_b5_tile_has_a_component():
    for tile in B5_TILES:
        component = "".join(part.capitalize() for part in tile.split("_")) + "Tile.svelte"
        assert (ROOT / "dashboard" / "src" / "tiles" / component).exists(), component
