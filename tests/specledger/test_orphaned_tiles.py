"""Tests for the orphaned_tiles check."""

from specledger.checks import ORPHANED_TILES, check_orphaned_tiles
from specledger.checks import (
    _app_has_tiles_loop,
    _app_rendered_components,
    _expected_component,
    _spec_tiles,
)


def details(violations):
    return [v.detail for v in violations]


def test_matching_tiles_pass(good_repo):
    assert check_orphaned_tiles(good_repo) == []


def test_orphaned_in_manifest(tmp_path, repo_builder):
    root = repo_builder(
        tmp_path,
        manifest_tiles=["tile_one", "tile_two", "ghost_tile"],
        spec_tiles=["tile_one", "tile_two"],
    )
    violations = check_orphaned_tiles(root)
    assert any("orphaned tile 'ghost_tile'" in d for d in details(violations))
    assert all(v.check == ORPHANED_TILES for v in violations)
    assert all(v.severity == "error" for v in violations)


def test_declared_in_spec_missing_from_manifest(tmp_path, repo_builder):
    root = repo_builder(
        tmp_path,
        manifest_tiles=["tile_one"],
        spec_tiles=["tile_one", "tile_two"],
    )
    violations = check_orphaned_tiles(root)
    assert any("'tile_two' declared in spec" in d for d in details(violations))


def test_missing_manifest_file(tmp_path, repo_builder):
    root = repo_builder(tmp_path)
    (root / "dashboard" / "src" / "tiles" / "registry.js").unlink()
    violations = check_orphaned_tiles(root)
    assert any("tile manifest not found" in d for d in details(violations))


def test_missing_spec_file(tmp_path, repo_builder):
    root = repo_builder(tmp_path)
    (root / "devharness-spec.md").unlink()
    violations = check_orphaned_tiles(root)
    assert any("spec not found" in d for d in details(violations))


def test_spec_parser_extracts_contiguous_bullets():
    text = (
        "preamble\n"
        "The dashboard renders exactly these 3 tiles.\n"
        "- `a_tile`\n"
        "- `b_tile`\n"
        "- `c_tile`\n"
        "\n"
        "- `not_a_tile_should_not_count`\n"
    )
    assert _spec_tiles(text) == ["a_tile", "b_tile", "c_tile"]


def test_spec_parser_empty_when_no_anchor():
    assert _spec_tiles("no manifest here\n- `x`\n") == []


# --- App.svelte render-coverage (new behavior) ---------------------------- #


def test_app_render_coverage_passes(good_repo):
    assert check_orphaned_tiles(good_repo) == []


def test_unrendered_manifest_tile_flagged(tmp_path, repo_builder):
    root = repo_builder(
        tmp_path,
        manifest_tiles=["tile_one", "tile_two"],
        spec_tiles=["tile_one", "tile_two"],
        app_rendered=["tile_one"],  # tile_two registered but never rendered
    )
    violations = check_orphaned_tiles(root)
    assert any(
        "'tile_two'" in d and "no rendered component" in d for d in details(violations)
    )
    assert all(v.check == ORPHANED_TILES for v in violations)
    assert all(v.severity == "error" for v in violations)


def test_proj_tile_covered_by_loop(tmp_path, repo_builder):
    root = repo_builder(
        tmp_path,
        manifest_tiles=["proj_role_state"],
        spec_tiles=["proj_role_state"],
        app_rendered=[],  # no dedicated component, but the projection loop is present
        app_include_loop=True,
    )
    assert check_orphaned_tiles(root) == []


def test_proj_tile_uncovered_without_loop(tmp_path, repo_builder):
    root = repo_builder(
        tmp_path,
        manifest_tiles=["proj_role_state"],
        spec_tiles=["proj_role_state"],
        app_rendered=[],
        app_include_loop=False,  # neither dedicated component nor loop
    )
    violations = check_orphaned_tiles(root)
    assert any(
        "'proj_role_state'" in d and "no rendered component" in d for d in details(violations)
    )


def test_missing_app_svelte(tmp_path, repo_builder):
    root = repo_builder(tmp_path)
    (root / "dashboard" / "src" / "App.svelte").unlink()
    violations = check_orphaned_tiles(root)
    assert any("app shell not found" in d for d in details(violations))


def test_component_name_mapping():
    assert _expected_component("candidate_queue") == "CandidateQueueTile"
    assert _expected_component("oss_intake") == "OssIntakeTile"
    assert _expected_component("plans") == "PlanTile"  # irregular alias


def test_app_parser_collects_rendered_and_loop():
    src = (
        "<script>\n"
        "  import Tile from './Tile.svelte';\n"
        "  import { TILES } from './tiles.js';\n"
        "  import FooTile from './tiles/FooTile.svelte';\n"
        "  import BarTile from './tiles/BarTile.svelte';\n"
        "</script>\n"
        "<main>\n"
        "  {#each TILES as tile (tile.table)}\n"
        "    <Tile title={tile.title} />\n"
        "  {/each}\n"
        "  <FooTile />\n"  # BarTile is imported but never rendered
        "</main>\n"
    )
    assert _app_rendered_components(src) == {"FooTile"}
    assert _app_has_tiles_loop(src) is True


def test_app_parser_no_loop():
    assert _app_has_tiles_loop("<main><FooTile /></main>") is False
