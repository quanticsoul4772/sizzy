"""Tests for the event_dispatch_coverage check."""

from specledger.checks import (
    EVENT_DISPATCH_COVERAGE,
    EVENT_LOG_ONLY,
    check_event_dispatch_coverage,
)
from specledger.checks import (
    _js_string_list,
    _registry_event_types,
    _svelte_subscribe_types,
    _tiles_eventtypes,
)


def details(violations):
    return [v.detail for v in violations]


def test_full_coverage_passes(good_repo):
    assert check_event_dispatch_coverage(good_repo) == []


def test_missing_from_dispatch_is_flagged(tmp_path, repo_builder):
    root = repo_builder(
        tmp_path,
        registry_events=["alpha", "beta", "gamma"],
        js_events=["alpha", "beta"],  # gamma missing
    )
    violations = check_event_dispatch_coverage(root)
    assert any("'gamma'" in d and "missing from the dashboard dispatch list" in d for d in details(violations))
    assert all(v.check == EVENT_DISPATCH_COVERAGE for v in violations)


def test_extra_in_dispatch_is_flagged(tmp_path, repo_builder):
    root = repo_builder(
        tmp_path,
        registry_events=["alpha", "beta"],
        js_events=["alpha", "beta", "ghost"],  # ghost not in registry
    )
    violations = check_event_dispatch_coverage(root)
    assert any("'ghost'" in d and "not in EVENT_TYPES" in d for d in details(violations))


def test_missing_registry_file(tmp_path, repo_builder):
    root = repo_builder(tmp_path)
    (root / "runtime" / "devharness" / "events" / "registry.py").unlink()
    violations = check_event_dispatch_coverage(root)
    assert any("event registry not found" in d for d in details(violations))


def test_missing_dispatch_file(tmp_path, repo_builder):
    root = repo_builder(tmp_path)
    (root / "dashboard" / "src" / "events.generated.js").unlink()
    violations = check_event_dispatch_coverage(root)
    assert any("dispatch list not found" in d for d in details(violations))


def test_registry_parser_extracts_annotated_dict():
    src = (
        "EVENT_TYPES: dict[str, type] = {\n"
        '    "a": object,\n'
        '    "b": object,\n'
        "}\n"
    )
    assert _registry_event_types(src) == ["a", "b"]


def test_registry_parser_extracts_plain_assign():
    src = 'EVENT_TYPES = {\n    "x": object,\n}\n'
    assert _registry_event_types(src) == ["x"]


def test_js_parser_strips_comments():
    src = (
        "export const EVENT_TYPES = [\n"
        "  // a comment 'fake'\n"
        "  'real_one',\n"
        "  'real_two',\n"
        "];\n"
    )
    assert _js_string_list(src, "EVENT_TYPES") == ["real_one", "real_two"]


# --- tile-handler coverage (new behavior) --------------------------------- #


def test_tile_handler_coverage_passes(good_repo):
    assert check_event_dispatch_coverage(good_repo) == []


def test_unhandled_event_is_flagged(tmp_path, repo_builder):
    root = repo_builder(
        tmp_path,
        registry_events=["alpha", "beta", "gamma"],
        js_events=["alpha", "beta", "gamma"],  # dispatch parity is fine
        handled_events=["alpha", "beta"],  # gamma handled by no tile
    )
    violations = check_event_dispatch_coverage(root)
    assert any("'gamma'" in d and "handled by no dashboard tile" in d for d in details(violations))
    assert all(v.check == EVENT_DISPATCH_COVERAGE for v in violations)


def test_allow_listed_event_not_flagged(tmp_path, repo_builder):
    allow = EVENT_LOG_ONLY[0]
    root = repo_builder(
        tmp_path,
        registry_events=["alpha", allow],
        js_events=["alpha", allow],
        handled_events=["alpha"],  # allow-listed type handled by no tile, but exempt
    )
    violations = check_event_dispatch_coverage(root)
    assert not any(allow in d for d in details(violations))


def test_event_handled_via_subscribe_array(tmp_path, repo_builder):
    root = repo_builder(
        tmp_path,
        registry_events=["alpha", "beta"],
        js_events=["alpha", "beta"],
        handled_events=["alpha"],  # beta is not in tiles.js eventTypes
        subscribe_events=["beta"],  # beta covered via an inline subscribe([...]) array
    )
    assert check_event_dispatch_coverage(root) == []


def test_missing_tiles_index_is_flagged(tmp_path, repo_builder):
    root = repo_builder(tmp_path)
    (root / "dashboard" / "src" / "tiles.js").unlink()
    violations = check_event_dispatch_coverage(root)
    assert any("tiles index not found" in d for d in details(violations))


def test_tiles_eventtypes_parser():
    src = (
        "export const TILES = [\n"
        "  { table: 'a', title: 'A', eventTypes: ['x', 'y'] },\n"
        "  { table: 'b', title: 'B', eventTypes: [] },\n"
        "];\n"
    )
    assert _tiles_eventtypes(src) == ["x", "y"]


def test_subscribe_parser_multiline():
    src = (
        "  unsubscribe = subscribe(\n"
        "    ['a', 'b', 'c'],\n"
        "    apply, () => (connected = true));\n"
    )
    assert _svelte_subscribe_types(src) == ["a", "b", "c"]
