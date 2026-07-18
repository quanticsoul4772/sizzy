"""Shared test fixtures for specledger.

Puts the repo root on sys.path so ``import specledger`` works regardless of the
pytest invocation directory (the package lives at the top-level ``specledger/``).
Also provides a builder for a synthetic, internally-consistent repo on disk.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from specledger.checks import _expected_component  # noqa: E402  (needs sys.path above)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _registry_py(event_types: list[str]) -> str:
    entries = "\n".join(f'    "{name}": object,' for name in event_types)
    return (
        '"""synthetic registry"""\n\n'
        "EVENT_TYPES: dict[str, type] = {\n"
        f"{entries}\n"
        "}\n"
    )


def _events_js(event_types: list[str]) -> str:
    entries = "\n".join(f"  '{name}'," for name in event_types)
    return "export const EVENT_TYPES = [\n" f"{entries}\n" "];\n"


def _tiles_js(tiles: list[str]) -> str:
    entries = "\n".join(f"  '{name}'," for name in tiles)
    return (
        "// Tile manifest (C7).\n"
        "export const TILE_MANIFEST = [\n"
        "  // a comment line that should be ignored\n"
        f"{entries}\n"
        "];\n"
    )


def _tiles_index_js(handled_events: list[str]) -> str:
    """The dashboard/src/tiles.js TILES array; carries handled events in eventTypes."""
    arr = ", ".join(f"'{name}'" for name in handled_events)
    return (
        "// Generic projection tiles; eventTypes feed the coverage check.\n"
        "export const TILES = [\n"
        f"  {{ table: 'proj_all', title: 'all events', eventTypes: [{arr}] }},\n"
        "];\n"
    )


def _app_svelte(components: list[str], include_loop: bool) -> str:
    imports = "\n".join(f"  import {c} from './tiles/{c}.svelte';" for c in components)
    loop = ""
    if include_loop:
        loop = (
            "  {#each TILES as tile (tile.table)}\n"
            "    <Tile title={tile.title} table={tile.table} eventTypes={tile.eventTypes} />\n"
            "  {/each}\n"
        )
    usages = "\n".join(f"  <{c} />" for c in components)
    return (
        "<script>\n"
        "  import Tile from './Tile.svelte';\n"
        "  import { TILES } from './tiles.js';\n"
        f"{imports}\n"
        "</script>\n\n"
        "<main>\n"
        f"{loop}"
        f"{usages}\n"
        "</main>\n"
    )


def _subscribe_svelte(events: list[str]) -> str:
    arr = ", ".join(f"'{name}'" for name in events)
    return (
        "<script>\n"
        "  import { subscribe } from '../events.js';\n"
        f"  subscribe([{arr}], apply, () => true);\n"
        "</script>\n"
        "<section>handler</section>\n"
    )


def _spec_md(tiles: list[str]) -> str:
    bullets = "\n".join(f"- `{name}`" for name in tiles)
    return (
        "### S9. Dashboard\n\n"
        f"**Tile manifest (C7).** The dashboard renders exactly these {len(tiles)} tiles.\n"
        f"{bullets}\n\n"
        "Some following paragraph that is not a bullet.\n"
    )


def build_repo(
    root: Path,
    *,
    migrations: list[str] | None = None,
    registry_events: list[str] | None = None,
    js_events: list[str] | None = None,
    manifest_tiles: list[str] | None = None,
    spec_tiles: list[str] | None = None,
    changelog: str | None = None,
    app_rendered: list[str] | None = None,
    app_include_loop: bool = True,
    handled_events: list[str] | None = None,
    subscribe_events: list[str] | None = None,
    git_init: bool = False,
) -> Path:
    """Materialise a synthetic devharness repo under ``root``.

    With no overrides the repo is internally consistent (no violations, given a
    changelog with no SHAs). Each argument overrides one source of truth.

    Dashboard render/coverage controls:
        app_rendered: tile names whose dedicated components App.svelte renders
            (default: every non-proj_ manifest tile).
        app_include_loop: emit the ``{#each TILES as tile}`` projection loop.
        handled_events: event types placed into tiles.js eventTypes (default: all
            registry_events, so coverage passes).
        subscribe_events: if set, written as an extra tile component whose inline
            ``subscribe([...])`` array also counts toward handled coverage.
    """
    if migrations is None:
        migrations = ["0001_initial", "0002_projections", "0003_artifacts"]
    if registry_events is None:
        registry_events = ["alpha", "beta", "gamma"]
    if js_events is None:
        js_events = list(registry_events)
    if manifest_tiles is None:
        manifest_tiles = ["tile_one", "tile_two"]
    if spec_tiles is None:
        spec_tiles = list(manifest_tiles)
    if changelog is None:
        changelog = "# Changelog\n\nNo closure SHAs here.\n"
    if app_rendered is None:
        app_rendered = [t for t in manifest_tiles if not t.startswith("proj_")]
    if handled_events is None:
        handled_events = list(registry_events)

    # repo markers
    _write(root / "devharness-spec.md", _spec_md(spec_tiles))
    (root / ".git").mkdir(exist_ok=True)  # marker; replaced by real git if git_init

    # migrations
    mig_dir = root / "schema" / "migrations"
    mig_dir.mkdir(parents=True, exist_ok=True)
    for name in migrations:
        _write(mig_dir / f"{name}.sql", "-- migration\nSELECT 1;\n")

    # event registry + dispatch list
    _write(root / "runtime" / "devharness" / "events" / "registry.py", _registry_py(registry_events))
    _write(root / "dashboard" / "src" / "events.generated.js", _events_js(js_events))

    # tiles manifest + spec already written
    _write(root / "dashboard" / "src" / "tiles" / "registry.js", _tiles_js(manifest_tiles))

    # dashboard app shell + tiles index (TILES) + optional subscribe handler
    components = [_expected_component(t) for t in app_rendered]
    _write(root / "dashboard" / "src" / "App.svelte", _app_svelte(components, app_include_loop))
    _write(root / "dashboard" / "src" / "tiles.js", _tiles_index_js(handled_events))
    if subscribe_events:
        _write(root / "dashboard" / "src" / "tiles" / "SubHandlerTile.svelte", _subscribe_svelte(subscribe_events))

    # changelog
    _write(root / "CHANGELOG.md", changelog)

    if git_init:
        _real_git_init(root)

    return root


def _real_git_init(root: Path) -> None:
    # Remove the marker dir so git can init cleanly.
    marker = root / ".git"
    if marker.exists() and marker.is_dir():
        import shutil

        shutil.rmtree(marker)
    env_args = dict(cwd=str(root), capture_output=True, text=True, check=True)
    subprocess.run(["git", "init"], **env_args)
    subprocess.run(["git", "config", "user.email", "test@example.com"], **env_args)
    subprocess.run(["git", "config", "user.name", "Test"], **env_args)
    subprocess.run(["git", "add", "-A"], **env_args)
    subprocess.run(["git", "commit", "-m", "initial"], **env_args)


def git_head_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo_builder():
    """Return the ``build_repo`` builder (callable with a target root)."""
    return build_repo


@pytest.fixture
def good_repo(tmp_path):
    """A fully-consistent synthetic repo (no violations)."""
    return build_repo(tmp_path)
