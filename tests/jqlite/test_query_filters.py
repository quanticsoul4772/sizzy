"""Tests for the filter calls ``select(f)`` and ``map(f)``.

Covers the parser (``Select`` / ``Map`` steps, including a recursively parsed
inner query and balanced-paren scanning), the streaming evaluator
(:func:`evaluate_stream`), and the CLI:

  * ``select(f)`` emits the input only when the inner filter is truthy (jq
    truthiness — everything except ``false`` and ``null``); a dropped value
    produces no result and exit 0.
  * ``map(f)`` applies ``f`` to each element of an array and returns the array
    of results; applied to a non-array it is a type error (exit 5).
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from jqlite.cli import main
from jqlite.errors import QueryError
from jqlite.eval import evaluate, evaluate_stream
from jqlite.parser import Field, Index, Iterate, Map, Select, parse_query

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #


def test_parse_select_identity_inner():
    assert parse_query("select(.)") == [Select(())]


def test_parse_select_field_inner():
    assert parse_query("select(.a)") == [Select((Field("a"),))]


def test_parse_select_chained_inner():
    assert parse_query("select(.a.b)") == [Select((Field("a"), Field("b")))]


def test_parse_select_iterate_inner():
    assert parse_query("select(.[])") == [Select((Iterate(),))]


def test_parse_map_identity_inner():
    assert parse_query("map(.)") == [Map(())]


def test_parse_map_field_inner():
    assert parse_query("map(.a)") == [Map((Field("a"),))]


def test_parse_map_index_inner():
    assert parse_query("map(.[0])") == [Map((Index(0),))]


def test_parse_map_inner_whitespace_is_stripped():
    assert parse_query("map( .a )") == [Map((Field("a"),))]


def test_parse_nested_filter_inner():
    # The inner argument is itself a filter; balanced-paren scanning must keep
    # the whole `select(.a)` as map's argument.
    assert parse_query("map(select(.a))") == [Map((Select((Field("a"),)),))]


def test_parse_map_then_index_juxtaposed():
    assert parse_query("map(.a)[0]") == [Map((Field("a"),)), Index(0)]


def test_parse_select_then_field_juxtaposed():
    assert parse_query("select(.a).b") == [Select((Field("a"),)), Field("b")]


@pytest.mark.parametrize(
    "bad",
    [
        "select",        # missing argument
        "map",           # missing argument
        "select(",       # unclosed paren
        "map(.a",        # unclosed paren
        "select()",      # empty argument is not a valid query
        "nope(.a)",      # unknown filter name
        "Select(.a)",    # case-sensitive: not a known filter
    ],
)
def test_parse_invalid_filter_raises(bad):
    with pytest.raises(QueryError):
        parse_query(bad)


# --------------------------------------------------------------------------- #
# evaluate_stream — select
# --------------------------------------------------------------------------- #


def test_select_truthy_field_keeps_input():
    src = {"a": 1, "b": 2}
    assert evaluate_stream(src, parse_query("select(.a)")) == [src]


def test_select_falsy_field_drops_input():
    assert evaluate_stream({"a": False}, parse_query("select(.a)")) == []


def test_select_null_field_drops_input():
    assert evaluate_stream({"a": None}, parse_query("select(.a)")) == []


def test_select_missing_field_drops_input():
    # A missing key addresses null, which is falsy.
    assert evaluate_stream({"b": 1}, parse_query("select(.a)")) == []


@pytest.mark.parametrize("truthy", [0, 1, -1, "", "x", [], {}, [0], {"k": 0}, True])
def test_select_jq_truthiness_keeps(truthy):
    # Everything except false and null is truthy in jq — including 0, "", [], {}.
    src = {"v": truthy}
    assert evaluate_stream(src, parse_query("select(.v)")) == [src]


@pytest.mark.parametrize("falsy", [False, None])
def test_select_jq_falsiness_drops(falsy):
    assert evaluate_stream({"v": falsy}, parse_query("select(.v)")) == []


def test_select_identity_on_scalar():
    assert evaluate_stream(7, parse_query("select(.)")) == [7]
    assert evaluate_stream(False, parse_query("select(.)")) == []
    assert evaluate_stream(None, parse_query("select(.)")) == []


def test_select_inner_type_error_propagates():
    # `.a` on a number is a type error, surfaced through select.
    with pytest.raises(QueryError) as excinfo:
        evaluate_stream(5, parse_query("select(.a)"))
    assert "field access '.a'" in str(excinfo.value)


def test_select_filters_within_an_iterated_stream():
    # `.[]` produces a stream, then select keeps only the truthy elements.
    src = [{"ok": True, "n": 1}, {"ok": False, "n": 2}, {"ok": True, "n": 3}]
    kept = evaluate_stream(src, parse_query(".[]select(.ok)"))
    assert kept == [{"ok": True, "n": 1}, {"ok": True, "n": 3}]


# --------------------------------------------------------------------------- #
# evaluate_stream — map
# --------------------------------------------------------------------------- #


def test_map_field_over_array_of_objects():
    src = [{"a": 1}, {"a": 2}, {"a": 3}]
    assert evaluate_stream(src, parse_query("map(.a)")) == [[1, 2, 3]]


def test_map_identity_returns_copy_of_array():
    assert evaluate_stream([1, 2, 3], parse_query("map(.)")) == [[1, 2, 3]]


def test_map_empty_array_returns_empty_array():
    assert evaluate_stream([], parse_query("map(.a)")) == [[]]


def test_map_index_over_array_of_arrays():
    src = [[10, 11], [20, 21]]
    assert evaluate_stream(src, parse_query("map(.[0])")) == [[10, 20]]


def test_map_missing_field_is_null_per_element():
    src = [{"a": 1}, {"b": 2}]
    assert evaluate_stream(src, parse_query("map(.a)")) == [[1, None]]


def test_map_with_iterate_inner_flattens():
    # map(.[]) collects every element of every inner array (jq: [.[] | .[]]).
    src = [[1, 2], [3], [4, 5]]
    assert evaluate_stream(src, parse_query("map(.[])")) == [[1, 2, 3, 4, 5]]


def test_map_with_select_inner_filters_elements():
    # map(select(.)) drops falsy elements (select emits empty for them).
    src = [1, False, 2, None, 3]
    assert evaluate_stream(src, parse_query("map(select(.))")) == [[1, 2, 3]]


def test_map_result_is_a_single_array():
    # map always yields exactly one result (the array), not a stream.
    assert evaluate(["x", "y"], parse_query("map(.)")) == ["x", "y"]


@pytest.mark.parametrize(
    "value,typename",
    [
        ({"a": 1}, "object"),
        ("hi", "string"),
        (1, "number"),
        (True, "boolean"),
        (None, "null"),
    ],
)
def test_map_on_non_array_raises(value, typename):
    with pytest.raises(QueryError) as excinfo:
        evaluate_stream(value, parse_query("map(.a)"))
    msg = str(excinfo.value)
    assert "map(...)" in msg
    assert typename in msg


def test_map_error_names_operation_type_and_value():
    with pytest.raises(QueryError) as excinfo:
        evaluate_stream(7, parse_query("map(.)"))
    assert str(excinfo.value) == (
        "map(...) requires an array, but the value is a number (7)"
    )


def test_map_inner_type_error_propagates():
    # An element is a scalar; `.a` on it is a type error that fails the map.
    with pytest.raises(QueryError):
        evaluate_stream([{"a": 1}, 2], parse_query("map(.a)"))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_select_truthy_emits_input():
    code, out, err = run_main('{"active": true, "id": 7}', ["select(.active)"])
    assert code == 0
    assert err == ""
    assert out == '{\n  "active": true,\n  "id": 7\n}\n'


def test_cli_select_falsy_emits_nothing_exit_0():
    code, out, err = run_main('{"active": false}', ["select(.active)"])
    assert code == 0
    assert out == ""
    assert err == ""


def test_cli_map_returns_array():
    code, out, err = run_main('[{"a": 1}, {"a": 2}]', ["map(.a)"])
    assert code == 0
    assert err == ""
    assert out == "[\n  1,\n  2\n]\n"


def test_cli_map_on_non_array_exits_5():
    code, out, err = run_main('{"a": 1}', ["map(.a)"])
    assert code == 5
    assert out == ""
    assert "map(...)" in err
    assert "object" in err


def test_cli_iterate_then_select_filters_stream():
    code, out, err = run_main(
        '[{"v": 1, "k": true}, {"v": 2, "k": false}]', [".[]select(.k)"]
    )
    assert code == 0
    assert out == '{\n  "v": 1,\n  "k": true\n}\n'


def test_cli_invalid_filter_exits_5():
    code, out, err = run_main('{"a": 1}', ["select("])
    assert code == 5
    assert out == ""
    assert err.startswith("jqlite:")


# --------------------------------------------------------------------------- #
# module entrypoint
# --------------------------------------------------------------------------- #


def test_module_entrypoint_map():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", "map(.a)"],
        input='[{"a": 1}, {"a": 2}, {"a": 3}]',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == "[\n  1,\n  2,\n  3\n]\n"
    assert proc.stderr == ""


def test_module_entrypoint_select_drop_exits_0():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", "select(.ok)"],
        input='{"ok": null}',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert proc.stderr == ""


def test_module_entrypoint_map_non_array_exits_5():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", "map(.a)"],
        input="42",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 5
    assert proc.stdout == ""
    assert "map(...)" in proc.stderr
