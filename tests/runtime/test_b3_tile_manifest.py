"""B3.8: TILE_MANIFEST lists 25 tile names matching the spec §S9 manifest."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "dashboard" / "src" / "tiles" / "registry.js"
SPEC = ROOT / "devharness-spec.md"


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


def test_registry_has_the_b3_tiles():
    # the live manifest has grown past B3 (28 at B4.7); the B3 tiles remain present
    assert {"maintenance", "adversarial"} <= _registry_tiles()


def test_registry_matches_spec_manifest():
    assert _registry_tiles() == _spec_tiles()
