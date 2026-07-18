"""Tests for the builtins ``keys``, ``length``, ``type`` and ``has(k)``.

Covers the parser (the nullary ``Keys`` / ``Length`` / ``Type`` steps and the
literal-argument ``Has`` step), the streaming evaluator
(:func:`evaluate_stream`), and the CLI exit-code / stderr behavior:

  * ``keys`` — sorted object keys, or array indices ``0..len-1``; a type error
    on a scalar (exit 5).
  * ``length`` — null -> 0, number -> absolute value, string -> codepoint count,
    array/object -> size; a boolean has no length (exit 5).
  * ``type`` — the JSON type name string for any value (never an error).
  * ``has(k)`` — object key membership (string key) / array index-in-range
    (integer key); a type mismatch or a scalar input is a type error (exit 5).

Builtin steps have no infix separator (jqlite v1 has no pipe), so they only
juxtapose after a bracket step (``.[0]keys``, ``.a[0]keys``) or appear inside a
filter argument (``map(keys)``); a bare ``.a keys`` would merge into one
identifier and is not valid jqlite.
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from jqlite.cli import main
from jqlite.errors import QueryError
from jqlite.eval import evaluate, evaluate_stream
from jqlite.parser import (
    Field,
    Has,
    Index,
    Iterate,
    Keys,
    Length,
    Map,
    Type,
    parse_query,
)

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


def test_parse_keys():
    assert parse_query("keys") == [Keys()]


def test_parse_length():
    assert parse_query("length") == [Length()]


def test_parse_type():
    assert parse_query("type") == [Type()]


def test_parse_has_string_key():
    assert parse_query('has("name")') == [Has("name")]


def test_parse_has_integer_key():
    assert parse_query("has(0)") == [Has(0)]


def test_parse_has_negative_integer_key():
    assert parse_query("has(-1)") == [Has(-1)]


def test_parse_has_argument_whitespace_is_stripped():
    assert parse_query('has( "name" )') == [Has("name")]


def test_parse_builtin_after_bracket_juxtaposed():
    assert parse_query(".a[0]keys") == [Field("a"), Index(0), Keys()]


def test_parse_iterate_then_keys_juxtaposed():
    assert parse_query(".[]keys") == [Iterate(), Keys()]


def test_parse_builtin_inside_map():
    assert parse_query("map(keys)") == [Map((Keys(),))]
    assert parse_query("map(length)") == [Map((Length(),))]
    assert parse_query('map(has("x"))') == [Map((Has("x"),))]


@pytest.mark.parametrize(
    "bad",
    [
        "keys(.a)",     # nullary builtin takes no argument
        "length(.a)",   # nullary builtin takes no argument
        "type(0)",      # nullary builtin takes no argument
        "has",          # missing argument
        "has(",         # unclosed paren
        "has()",        # empty argument
        "has(.a)",      # argument must be a literal, not a query
        "has(1.5)",     # float key is not allowed
        "has(true)",    # boolean key is not allowed
        "has(null)",    # null key is not allowed
        "has([0])",     # array key is not allowed
        "Keys",         # case-sensitive: not a builtin
    ],
)
def test_parse_invalid_builtin_raises(bad):
    with pytest.raises(QueryError):
        parse_query(bad)


# --------------------------------------------------------------------------- #
# evaluate_stream — keys
# --------------------------------------------------------------------------- #


def test_keys_object_returns_sorted_keys():
    assert evaluate({"b": 1, "a": 2, "c": 3}, parse_query("keys")) == ["a", "b", "c"]


def test_keys_empty_object():
    assert evaluate({}, parse_query("keys")) == []


def test_keys_array_returns_indices():
    assert evaluate(["x", "y", "z"], parse_query("keys")) == [0, 1, 2]


def test_keys_empty_array():
    assert evaluate([], parse_query("keys")) == []


@pytest.mark.parametrize(
    "value,typename",
    [
        (1, "number"),
        ("hi", "string"),
        (True, "boolean"),
        (None, "null"),
    ],
)
def test_keys_on_scalar_raises(value, typename):
    with pytest.raises(QueryError) as excinfo:
        evaluate(value, parse_query("keys"))
    msg = str(excinfo.value)
    assert "keys requires an object or array" in msg
    assert typename in msg


# --------------------------------------------------------------------------- #
# evaluate_stream — length
# --------------------------------------------------------------------------- #


def test_length_null_is_zero():
    assert evaluate(None, parse_query("length")) == 0


def test_length_string_is_codepoint_count():
    assert evaluate("hello", parse_query("length")) == 5
    assert evaluate("", parse_query("length")) == 0
    assert evaluate("héllo", parse_query("length")) == 5


def test_length_array_is_element_count():
    assert evaluate([1, 2, 3], parse_query("length")) == 3
    assert evaluate([], parse_query("length")) == 0


def test_length_object_is_key_count():
    assert evaluate({"a": 1, "b": 2}, parse_query("length")) == 2
    assert evaluate({}, parse_query("length")) == 0


@pytest.mark.parametrize(
    "number,expected",
    [(0, 0), (7, 7), (-3, 3), (3.5, 3.5), (-3.5, 3.5)],
)
def test_length_number_is_absolute_value(number, expected):
    assert evaluate(number, parse_query("length")) == expected


@pytest.mark.parametrize("value", [True, False])
def test_length_on_boolean_raises(value):
    with pytest.raises(QueryError) as excinfo:
        evaluate(value, parse_query("length"))
    assert "boolean" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# evaluate_stream — type
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,typename",
    [
        (None, "null"),
        (True, "boolean"),
        (False, "boolean"),
        (1, "number"),
        (1.5, "number"),
        ("s", "string"),
        ([1, 2], "array"),
        ({"a": 1}, "object"),
    ],
)
def test_type_returns_json_type_name(value, typename):
    assert evaluate(value, parse_query("type")) == typename


def test_type_never_errors_on_any_json():
    # type is total over JSON values.
    for value in (None, True, 0, "", [], {}):
        assert isinstance(evaluate(value, parse_query("type")), str)


# --------------------------------------------------------------------------- #
# evaluate_stream — has
# --------------------------------------------------------------------------- #


def test_has_object_key_present():
    assert evaluate({"a": 1, "b": 2}, parse_query('has("a")')) is True


def test_has_object_key_absent():
    assert evaluate({"a": 1}, parse_query('has("x")')) is False


def test_has_object_key_present_even_when_value_falsy():
    # Membership is about the key, not the value.
    assert evaluate({"a": None}, parse_query('has("a")')) is True
    assert evaluate({"a": False}, parse_query('has("a")')) is True


def test_has_array_index_in_range():
    assert evaluate([10, 20, 30], parse_query("has(0)")) is True
    assert evaluate([10, 20, 30], parse_query("has(2)")) is True


def test_has_array_index_out_of_range():
    assert evaluate([10, 20, 30], parse_query("has(3)")) is False
    # jq: negative indices are never "had".
    assert evaluate([10, 20, 30], parse_query("has(-1)")) is False


def test_has_empty_array_or_object():
    assert evaluate([], parse_query("has(0)")) is False
    assert evaluate({}, parse_query('has("a")')) is False


def test_has_string_key_on_array_raises():
    with pytest.raises(QueryError) as excinfo:
        evaluate([1, 2], parse_query('has("0")'))
    assert "integer index" in str(excinfo.value)


def test_has_integer_key_on_object_raises():
    with pytest.raises(QueryError) as excinfo:
        evaluate({"a": 1}, parse_query("has(0)"))
    assert "string key" in str(excinfo.value)


@pytest.mark.parametrize(
    "value,typename",
    [
        (1, "number"),
        ("hi", "string"),
        (True, "boolean"),
        (None, "null"),
    ],
)
def test_has_on_scalar_raises(value, typename):
    with pytest.raises(QueryError) as excinfo:
        evaluate(value, parse_query('has("a")'))
    msg = str(excinfo.value)
    assert "has(...)" in msg
    assert typename in msg


# --------------------------------------------------------------------------- #
# composition with other steps
# --------------------------------------------------------------------------- #


def test_map_keys_over_array_of_objects():
    src = [{"b": 1, "a": 2}, {"d": 3, "c": 4}]
    assert evaluate(src, parse_query("map(keys)")) == [["a", "b"], ["c", "d"]]


def test_map_length_over_array_of_arrays():
    assert evaluate([[1, 2], [3], []], parse_query("map(length)")) == [2, 1, 0]


def test_iterate_then_type_streams_type_names():
    src = [1, "x", None, [0], {"k": 1}]
    assert evaluate_stream(src, parse_query(".[]type")) == [
        "number",
        "string",
        "null",
        "array",
        "object",
    ]


def test_index_then_keys():
    assert evaluate([{"y": 1, "x": 2}], parse_query(".[0]keys")) == ["x", "y"]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_keys_object():
    code, out, err = run_main('{"b": 1, "a": 2}', ["keys"])
    assert code == 0
    assert err == ""
    assert out == '[\n  "a",\n  "b"\n]\n'


def test_cli_length_string():
    code, out, err = run_main('"hello"', ["length"])
    assert code == 0
    assert out == "5\n"


def test_cli_type_array():
    code, out, err = run_main("[1, 2, 3]", ["type"])
    assert code == 0
    assert out == '"array"\n'


def test_cli_has_true():
    code, out, err = run_main('{"a": 1}', ['has("a")'])
    assert code == 0
    assert out == "true\n"


def test_cli_has_false():
    code, out, err = run_main("[1, 2]", ["has(5)"])
    assert code == 0
    assert out == "false\n"


def test_cli_keys_on_scalar_exits_5():
    code, out, err = run_main("42", ["keys"])
    assert code == 5
    assert out == ""
    assert "keys requires an object or array" in err
    assert err.startswith("jqlite:")


def test_cli_length_on_boolean_exits_5():
    code, out, err = run_main("true", ["length"])
    assert code == 5
    assert out == ""
    assert "boolean" in err


def test_cli_has_type_mismatch_exits_5():
    code, out, err = run_main("[1, 2]", ['has("a")'])
    assert code == 5
    assert out == ""
    assert "integer index" in err


def test_cli_invalid_builtin_exits_5():
    code, out, err = run_main('{"a": 1}', ["keys(.a)"])
    assert code == 5
    assert out == ""
    assert err.startswith("jqlite:")


# --------------------------------------------------------------------------- #
# module entrypoint
# --------------------------------------------------------------------------- #


def test_module_entrypoint_keys():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", "keys"],
        input='{"b": 1, "a": 2}',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == '[\n  "a",\n  "b"\n]\n'
    assert proc.stderr == ""


def test_module_entrypoint_has_false_exits_0():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", "has(9)"],
        input="[1, 2, 3]",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == "false\n"
    assert proc.stderr == ""


def test_module_entrypoint_length_on_boolean_exits_5():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", "length"],
        input="false",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 5
    assert proc.stdout == ""
    assert "boolean" in proc.stderr
