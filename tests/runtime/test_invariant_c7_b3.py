"""B3.8: C7 re-enforced at 25 tiles — spec §S9 manifest == dashboard registry."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot


def test_c7_passes_at_25():
    assert boot.check_dashboard_tile_coverage() is True


def test_c7_still_registered_under_c7():
    assert boot.REQUIRED_GATES["check_dashboard_tile_coverage"] == "C7"


def test_c7_fails_closed_on_b3_mismatch(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("**Tile manifest (C7).** tiles:\n- `maintenance`\n- `adversarial`\n\nend\n", encoding="utf-8")
    registry = tmp_path / "registry.js"
    registry.write_text("export const TILE_MANIFEST = ['maintenance'];\n", encoding="utf-8")  # missing adversarial
    with pytest.raises(boot.BootError):
        boot.check_dashboard_tile_coverage(spec_path=spec, registry_path=registry)


def test_c7_matched_synthetic_passes(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("**Tile manifest (C7).** tiles:\n- `maintenance`\n- `adversarial`\n\nend\n", encoding="utf-8")
    registry = tmp_path / "registry.js"
    registry.write_text("export const TILE_MANIFEST = ['maintenance', 'adversarial'];\n", encoding="utf-8")
    assert boot.check_dashboard_tile_coverage(spec_path=spec, registry_path=registry) is True
