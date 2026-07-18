"""The four repo-consistency checks.

Each check takes the repo root and returns a list of ``Violation`` (empty when
the check passes). All checks are read-only: they only read files and, for the
changelog check, run read-only ``git rev-parse``.
"""

import ast
import re
from pathlib import Path

from specledger.gitprobe import GitRunner, is_git_repo, real_git_runner, sha_resolvable
from specledger.model import SEVERITY_ERROR, Violation

# Check ids (also the public ordering used by run_all_checks).
MIGRATION_CONTIGUITY = "migration_contiguity"
EVENT_DISPATCH_COVERAGE = "event_dispatch_coverage"
CHANGELOG_SHA_RESOLVABLE = "changelog_sha_resolvable"
ORPHANED_TILES = "orphaned_tiles"

# Source-of-truth file locations (relative to repo root).
MIGRATIONS_DIR = Path("schema") / "migrations"
REGISTRY_PY = Path("runtime") / "devharness" / "events" / "registry.py"
EVENTS_JS = Path("dashboard") / "src" / "events.generated.js"
TILES_JS = Path("dashboard") / "src" / "tiles" / "registry.js"
APP_SVELTE = Path("dashboard") / "src" / "App.svelte"
TILES_INDEX_JS = Path("dashboard") / "src" / "tiles.js"
TILES_DIR = Path("dashboard") / "src" / "tiles"
SPEC_MD = Path("devharness-spec.md")
CHANGELOG_MD = Path("CHANGELOG.md")

# Tiles whose dedicated Svelte component name is irregular and cannot be derived
# by the snake_case -> PascalCase + 'Tile' rule (e.g. the plural manifest entry
# 'plans' renders the singular PlanTile component). Keep this map small and
# documented: every entry here is an intentional naming exception, not a bug.
TILE_COMPONENT_ALIASES = {
    "plans": "PlanTile",
}

# Event types that exist in the catalog by design but are intentionally
# event-log-only: no dashboard tile renders them. These are excluded from the
# tile-handler coverage check below. Adding a tile that handles one of these is
# fine; what this list asserts is that the *absence* of a handler is deliberate.
EVENT_LOG_ONLY = (
    "research_started",
    "director_decision",
    "tier_floor_violation",
    "oss_scope_boundary_derived",
    # the enacted gate-change record — its EFFECT is live (the gate screens it) and the state is queryable
    # via proj_enacted_gate_changes; a dedicated tile is a deliberate-deferred nicety.
    "gate_change_enacted",
    # operator-authorized prune of an expired trust grant — an audit record; the live trust state is on
    # the calibrated-trust tile (this just removes an already-invalid expired grant).
    "trust_grant_pruned",
)


def _err(check: str, detail: str) -> Violation:
    return Violation(check=check, severity=SEVERITY_ERROR, detail=detail)


# --------------------------------------------------------------------------- #
# Check 1: migration_contiguity
# --------------------------------------------------------------------------- #


def check_migration_contiguity(repo_root: Path) -> list[Violation]:
    """schema/migrations/*.sql must be numbered contiguously from 0001."""
    check = MIGRATION_CONTIGUITY
    directory = repo_root / MIGRATIONS_DIR
    if not directory.is_dir():
        return [_err(check, f"migrations directory not found: {MIGRATIONS_DIR.as_posix()}")]

    numbered: list[tuple[int, str]] = []
    violations: list[Violation] = []
    for path in sorted(directory.glob("*.sql")):
        match = re.match(r"^(\d+)_", path.name)
        if not match:
            violations.append(
                _err(check, f"migration filename has no numeric prefix: {path.name}")
            )
            continue
        prefix, n = match.group(1), int(match.group(1))
        # the prefix must be exactly zero-padded to 4 digits (e.g. 0007, never 7 or 00007) — the runner
        # orders migrations by name, so an un-padded prefix sorts wrong AND would collide with the padded
        # form. The duplicate/gap checks below run on the parsed int regardless.
        if prefix != f"{n:04d}":
            violations.append(
                _err(check, f"migration {path.name!r} prefix is not zero-padded to 4 digits (expected {n:04d}_)")
            )
        numbered.append((n, path.name))

    if not numbered:
        violations.append(_err(check, "no numbered migration files found"))
        return violations

    numbers = [n for n, _ in numbered]
    counts: dict[int, int] = {}
    for n in numbers:
        counts[n] = counts.get(n, 0) + 1
    for n in sorted(d for d, c in counts.items() if c > 1):
        violations.append(_err(check, f"duplicate migration number {n:04d}"))

    unique = sorted(counts)
    if unique[0] != 1:
        violations.append(
            _err(check, f"migration numbering starts at {unique[0]:04d}, expected 0001")
        )
    full_range = set(range(unique[0], unique[-1] + 1))
    for missing in sorted(full_range - set(unique)):
        violations.append(_err(check, f"missing migration number {missing:04d} (gap in sequence)"))

    return violations


# --------------------------------------------------------------------------- #
# Check 2: event_dispatch_coverage
# --------------------------------------------------------------------------- #


def _registry_event_types(source: str) -> list[str]:
    """Extract the EVENT_TYPES dict keys from registry.py source via AST.

    Stdlib-only: we parse the source rather than import the module (which would
    require msgspec and execute side effects).
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        target_names: list[str] = []
        value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_names = [node.target.id]
            value = node.value
        elif isinstance(node, ast.Assign):
            target_names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        if "EVENT_TYPES" in target_names and isinstance(value, ast.Dict):
            keys: list[str] = []
            for key in value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.append(key.value)
            return keys
    raise ValueError("EVENT_TYPES dict not found in registry source")


def _js_string_list(source: str, name: str) -> list[str]:
    """Extract the string literals from a ``const <name> = [ ... ];`` JS array.

    JS line comments (``// ...``) are stripped before extracting literals.
    """
    match = re.search(rf"{re.escape(name)}\s*=\s*\[(.*?)\]", source, re.DOTALL)
    if not match:
        raise ValueError(f"{name} array not found")
    body = re.sub(r"//[^\n]*", "", match.group(1))
    return re.findall(r"['\"]([A-Za-z0-9_]+)['\"]", body)


def _tiles_eventtypes(source: str) -> list[str]:
    """Extract every event type listed in the ``eventTypes: [ ... ]`` arrays.

    Reads the ``TILES`` array in dashboard/src/tiles.js: each tile entry carries
    an ``eventTypes`` list naming the event types that feed it.
    """
    out: list[str] = []
    for body in re.findall(r"eventTypes\s*:\s*\[(.*?)\]", source, re.DOTALL):
        body = re.sub(r"//[^\n]*", "", body)
        out.extend(re.findall(r"['\"]([A-Za-z0-9_]+)['\"]", body))
    return out


def _svelte_subscribe_types(source: str) -> list[str]:
    """Extract event types from inline ``subscribe([ ... ], ...)`` calls.

    Dedicated tile components subscribe to their event types directly; the first
    argument is the array of handled event-type strings.
    """
    out: list[str] = []
    for body in re.findall(r"subscribe\s*\(\s*\[(.*?)\]", source, re.DOTALL):
        body = re.sub(r"//[^\n]*", "", body)
        out.extend(re.findall(r"['\"]([A-Za-z0-9_]+)['\"]", body))
    return out


def _handled_event_types(repo_root: Path) -> set[str]:
    """Union of event types handled by any dashboard tile.

    Sources: the ``eventTypes`` arrays in dashboard/src/tiles.js plus every
    inline ``subscribe([...])`` array in the dedicated dashboard/src/tiles/*.svelte
    components.
    """
    handled: set[str] = set()
    tiles_index = repo_root / TILES_INDEX_JS
    if tiles_index.is_file():
        handled.update(_tiles_eventtypes(tiles_index.read_text(encoding="utf-8")))
    tiles_dir = repo_root / TILES_DIR
    if tiles_dir.is_dir():
        for svelte in sorted(tiles_dir.glob("*.svelte")):
            handled.update(_svelte_subscribe_types(svelte.read_text(encoding="utf-8")))
    return handled


def _check_tile_event_coverage(repo_root: Path, registry_types: list[str]) -> list[Violation]:
    """Every EVENT_TYPES entry must be handled by a tile or be event-log-only."""
    check = EVENT_DISPATCH_COVERAGE
    tiles_index = repo_root / TILES_INDEX_JS
    if not tiles_index.is_file():
        return [_err(check, f"tiles index not found: {TILES_INDEX_JS.as_posix()}")]

    handled = _handled_event_types(repo_root)
    allow = set(EVENT_LOG_ONLY)
    violations: list[Violation] = []
    for name in registry_types:
        if name in handled or name in allow:
            continue
        violations.append(
            _err(
                check,
                f"event type '{name}' is in EVENT_TYPES but handled by no dashboard tile "
                f"and not in the event-log-only allow-list",
            )
        )
    return violations


def check_event_dispatch_coverage(repo_root: Path) -> list[Violation]:
    """Every EVENT_TYPES entry must appear in the dashboard dispatch list and be
    handled by a dashboard tile (or be a named event-log-only type)."""
    check = EVENT_DISPATCH_COVERAGE
    registry_path = repo_root / REGISTRY_PY
    events_js_path = repo_root / EVENTS_JS

    if not registry_path.is_file():
        return [_err(check, f"event registry not found: {REGISTRY_PY.as_posix()}")]
    if not events_js_path.is_file():
        return [_err(check, f"dashboard dispatch list not found: {EVENTS_JS.as_posix()}")]

    try:
        registry_types = _registry_event_types(registry_path.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError) as exc:
        return [_err(check, f"could not parse EVENT_TYPES from {REGISTRY_PY.as_posix()}: {exc}")]
    try:
        dispatch_types = _js_string_list(events_js_path.read_text(encoding="utf-8"), "EVENT_TYPES")
    except ValueError as exc:
        return [_err(check, f"could not parse dispatch list from {EVENTS_JS.as_posix()}: {exc}")]

    dispatch_set = set(dispatch_types)
    registry_set = set(registry_types)
    violations: list[Violation] = []
    for name in registry_types:
        if name not in dispatch_set:
            violations.append(
                _err(check, f"event type '{name}' is in EVENT_TYPES but missing from the dashboard dispatch list")
            )
    for name in dispatch_types:
        if name not in registry_set:
            violations.append(
                _err(check, f"event type '{name}' is in the dashboard dispatch list but not in EVENT_TYPES")
            )

    # Additional: tile-handler coverage (tiles.js eventTypes + subscribe arrays).
    violations.extend(_check_tile_event_coverage(repo_root, registry_types))
    return violations


# --------------------------------------------------------------------------- #
# Check 3: changelog_sha_resolvable
# --------------------------------------------------------------------------- #

# Backtick-wrapped 7-40 char lowercase-hex tokens are closure SHAs. Migration
# numbers (e.g. `0023`) are 4 digits and excluded by the length bound.
_SHA_RE = re.compile(r"`([0-9a-f]{7,40})`")


def _changelog_shas(text: str) -> list[str]:
    seen: list[str] = []
    for sha in _SHA_RE.findall(text):
        if sha not in seen:
            seen.append(sha)
    return seen


def check_changelog_sha_resolvable(
    repo_root: Path, *, git_runner: GitRunner = real_git_runner
) -> list[Violation]:
    """Every closure SHA referenced in CHANGELOG.md must resolve in git."""
    check = CHANGELOG_SHA_RESOLVABLE
    changelog_path = repo_root / CHANGELOG_MD
    if not changelog_path.is_file():
        return [_err(check, f"changelog not found: {CHANGELOG_MD.as_posix()}")]

    shas = _changelog_shas(changelog_path.read_text(encoding="utf-8"))

    if not is_git_repo(repo_root, runner=git_runner):
        return [_err(check, "not a git repository; cannot resolve CHANGELOG SHAs")]

    violations: list[Violation] = []
    for sha in shas:
        if not sha_resolvable(repo_root, sha, runner=git_runner):
            violations.append(_err(check, f"CHANGELOG SHA '{sha}' does not resolve to a commit in git"))
    return violations


# --------------------------------------------------------------------------- #
# Check 4: orphaned_tiles
# --------------------------------------------------------------------------- #


def _spec_tiles(text: str) -> list[str]:
    """Extract the §S9 tile-manifest bullet list from the spec.

    The manifest is the contiguous run of ``- `tile_name`` bullets immediately
    following the "renders exactly these N tiles" sentence.
    """
    tiles: list[str] = []
    collecting = False
    for line in text.splitlines():
        if not collecting:
            if "renders exactly these" in line:
                collecting = True
            continue
        match = re.match(r"^- `([a-z0-9_]+)`\s*$", line)
        if match:
            tiles.append(match.group(1))
        elif tiles:
            break
    return tiles


def _pascal_case(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_") if part)


def _expected_component(tile: str) -> str:
    """Map a TILE_MANIFEST entry to its dedicated Svelte component name.

    snake_case -> PascalCase + 'Tile' (candidate_queue -> CandidateQueueTile),
    with the irregular names in TILE_COMPONENT_ALIASES taking precedence.
    """
    if tile in TILE_COMPONENT_ALIASES:
        return TILE_COMPONENT_ALIASES[tile]
    return _pascal_case(tile) + "Tile"


def _app_rendered_components(source: str) -> set[str]:
    """Tile components that are both imported from ./tiles/ and rendered in App.svelte."""
    imported = set(re.findall(r"import\s+(\w+)\s+from\s+['\"]\./tiles/[\w./-]+\.svelte['\"]", source))
    rendered: set[str] = set()
    for name in imported:
        if re.search(r"<" + re.escape(name) + r"[\s/>]", source):
            rendered.add(name)
    return rendered


def _app_has_tiles_loop(source: str) -> bool:
    """Whether App.svelte contains the ``{#each TILES as tile}`` projection loop."""
    return re.search(r"\{#each\s+TILES\s+as\s+tile\b", source) is not None


def _check_app_render_coverage(repo_root: Path, manifest_tiles: list[str]) -> list[Violation]:
    """Every TILE_MANIFEST entry must be rendered by App.svelte.

    A tile is covered if its dedicated component is imported+rendered, or (for a
    ``proj_*`` projection tile) the ``{#each TILES as tile}`` loop is present.
    """
    check = ORPHANED_TILES
    app_path = repo_root / APP_SVELTE
    if not app_path.is_file():
        return [_err(check, f"dashboard app shell not found: {APP_SVELTE.as_posix()}")]

    source = app_path.read_text(encoding="utf-8")
    rendered = _app_rendered_components(source)
    has_loop = _app_has_tiles_loop(source)

    violations: list[Violation] = []
    for tile in manifest_tiles:
        component = _expected_component(tile)
        if component in rendered:
            continue
        if tile.startswith("proj_") and has_loop:
            continue
        violations.append(
            _err(
                check,
                f"TILE_MANIFEST entry '{tile}' has no rendered component '{component}' in "
                f"{APP_SVELTE.as_posix()} and no proj_* loop coverage",
            )
        )
    return violations


def check_orphaned_tiles(repo_root: Path) -> list[Violation]:
    """The dashboard TILE_MANIFEST must match spec §S9 and be rendered by App.svelte."""
    check = ORPHANED_TILES
    tiles_js_path = repo_root / TILES_JS
    spec_path = repo_root / SPEC_MD

    if not tiles_js_path.is_file():
        return [_err(check, f"tile manifest not found: {TILES_JS.as_posix()}")]
    if not spec_path.is_file():
        return [_err(check, f"spec not found: {SPEC_MD.as_posix()}")]

    try:
        manifest_tiles = _js_string_list(tiles_js_path.read_text(encoding="utf-8"), "TILE_MANIFEST")
    except ValueError as exc:
        return [_err(check, f"could not parse TILE_MANIFEST from {TILES_JS.as_posix()}: {exc}")]
    spec_tiles = _spec_tiles(spec_path.read_text(encoding="utf-8"))

    if not spec_tiles:
        return [_err(check, "no tile manifest found in spec §S9")]

    manifest_set = set(manifest_tiles)
    spec_set = set(spec_tiles)
    violations: list[Violation] = []
    for tile in manifest_tiles:
        if tile not in spec_set:
            violations.append(
                _err(check, f"orphaned tile '{tile}' in dashboard manifest, absent from spec §S9")
            )
    for tile in spec_tiles:
        if tile not in manifest_set:
            violations.append(
                _err(check, f"tile '{tile}' declared in spec §S9 but absent from dashboard manifest")
            )

    # Additional: every manifest tile must be rendered by the App.svelte shell.
    violations.extend(_check_app_render_coverage(repo_root, manifest_tiles))
    return violations


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

CHECKS = (
    check_migration_contiguity,
    check_event_dispatch_coverage,
    check_changelog_sha_resolvable,
    check_orphaned_tiles,
)


def run_all_checks(repo_root: Path) -> list[Violation]:
    """Run every check against ``repo_root`` and return all violations in order."""
    violations: list[Violation] = []
    for check in CHECKS:
        violations.extend(check(repo_root))
    return violations
