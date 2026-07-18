"""B4.7: the 3 B4 OSS tiles are present in TILE_MANIFEST and it matches the spec §S9 manifest.

(B4 brought the manifest to 28; spec rev 0.3.31 later removed 7 feedless B0 generic placeholders,
so the B4-era floor is now 21 — 5 generic + 6 B1 + 5 B2 + 2 B3 + 3 B4 — with the exact total pinned
by test_b5_tile_manifest.)"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "dashboard" / "src" / "tiles" / "registry.js"
SPEC = ROOT / "devharness-spec.md"

B4_TILES = {"oss_intake", "oss_enforcement", "oss_branch"}


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


def test_registry_has_b4_tiles():
    # the exact total is pinned by the latest sub-phase's tile_manifest test (B5.6 → 32, then
    # rev 0.3.31 → 25); here we just assert the 3 B4 tiles survive and the manifest is >= the B4 floor.
    tiles = _registry_tiles()
    assert len(tiles) >= 21
    assert B4_TILES <= tiles


def test_spec_manifest_has_b4_tiles():
    assert len(_spec_tiles()) >= 21
    assert B4_TILES <= _spec_tiles()


def test_registry_matches_spec_manifest():
    assert _registry_tiles() == _spec_tiles()
