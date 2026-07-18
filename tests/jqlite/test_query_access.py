"""Tests for field access (.a, .a.b) and index access (.[N]).

Covers the parser, the evaluator, and the CLI exit-code / stderr behavior for
the two type-error cases: field access on a non-object and indexing a
non-indexable value (each exit 5).
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jqlite.cli import main
from jqlite.errors import QueryError
from jqlite.eval import evaluate, json_type
from jqlite.parser import Field, Index, parse_query

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


def test_parse_identity():
    assert parse_query(".") == []


def test_parse_single_field():
    assert parse_query(".a") == [Field("a")]


def test_parse_chained_fields():
    assert parse_query(".a.b") == [Field("a"), Field("b")]


def test_parse_deep_chain():
    assert parse_query(".a.b.c") == [Field("a"), Field("b"), Field("c")]


def test_parse_index():
    assert parse_query(".[0]") == [Index(0)]


def test_parse_negative_index():
    assert parse_query(".[-1]") == [Index(-1)]


def test_parse_field_then_index():
    assert parse_query(".a[0]") == [Field("a"), Index(0)]


def test_parse_field_dot_then_index():
    assert parse_query(".a.[0]") == [Field("a"), Index(0)]


def test_parse_chained_index():
    assert parse_query(".[0][1]") == [Index(0), Index(1)]


def test_parse_identifier_with_digits_and_underscore():
    assert parse_query(".a_1.b2") == [Field("a_1"), Field("b2")]


@pytest.mark.parametrize(
    "bad",
    [
        "",          # empty
        "a",         # no leading dot
        ".1a",       # field name cannot start with a digit
        ".a.",       # trailing dot
        ".[1.5]",    # non-integer index
        ".[x]",      # non-integer index
        ".[0",       # unclosed bracket
        "..",        # recursive descent is out of scope
    ],
)
def test_parse_invalid_raises_query_error(bad):
    with pytest.raises(QueryError):
        parse_query(bad)


# --------------------------------------------------------------------------- #
# evaluate — success
# --------------------------------------------------------------------------- #


def test_eval_identity_returns_value():
    obj = {"a": 1}
    assert evaluate(obj, parse_query(".")) is obj


def test_eval_field():
    assert evaluate({"a": 1, "b": 2}, parse_query(".a")) == 1


def test_eval_chained_field():
    assert evaluate({"a": {"b": 42}}, parse_query(".a.b")) == 42


def test_eval_missing_field_is_null():
    assert evaluate({"a": 1}, parse_query(".x")) is None


def test_eval_field_value_can_be_any_json():
    assert evaluate({"a": [1, 2]}, parse_query(".a")) == [1, 2]
    assert evaluate({"a": None}, parse_query(".a")) is None


def test_eval_index():
    assert evaluate([10, 20, 30], parse_query(".[1]")) == 20


def test_eval_negative_index():
    assert evaluate([10, 20, 30], parse_query(".[-1]")) == 30


def test_eval_index_out_of_range_is_null():
    assert evaluate([1, 2], parse_query(".[5]")) is None
    assert evaluate([1, 2], parse_query(".[-9]")) is None


def test_eval_field_then_index():
    assert evaluate({"a": [7, 8]}, parse_query(".a[1]")) == 8


def test_eval_index_then_field():
    assert evaluate([{"k": "v"}], parse_query(".[0].k")) == "v"


# --------------------------------------------------------------------------- #
# evaluate — type errors
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,typename",
    [
        (1, "number"),
        (3.5, "number"),
        ("hi", "string"),
        ([1, 2], "array"),
        (True, "boolean"),
        (None, "null"),
    ],
)
def test_field_access_on_non_object_raises(value, typename):
    with pytest.raises(QueryError) as excinfo:
        evaluate(value, parse_query(".a"))
    msg = str(excinfo.value)
    assert "field access '.a'" in msg
    assert typename in msg


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
def test_index_on_non_array_raises(value, typename):
    with pytest.raises(QueryError) as excinfo:
        evaluate(value, parse_query(".[0]"))
    msg = str(excinfo.value)
    assert "index access '[0]'" in msg
    assert typename in msg


def test_field_error_names_operation_type_and_value():
    with pytest.raises(QueryError) as excinfo:
        evaluate(1, parse_query(".a"))
    assert str(excinfo.value) == (
        "field access '.a' requires an object, but the value is a number (1)"
    )


def test_index_error_names_operation_type_and_value():
    with pytest.raises(QueryError) as excinfo:
        evaluate("hi", parse_query(".[0]"))
    assert str(excinfo.value) == (
        'index access \'[0]\' requires an array, but the value is a string ("hi")'
    )


def test_json_type_names():
    assert json_type(None) == "null"
    assert json_type(True) == "boolean"
    assert json_type(1) == "number"
    assert json_type(1.5) == "number"
    assert json_type("s") == "string"
    assert json_type([]) == "array"
    assert json_type({}) == "object"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_field_access():
    code, out, err = run_main('{"a": 1, "b": 2}', [".a"])
    assert out == "1\n"


def test_cli_chained_field_access():
    code, out, err = run_main('{"a": {"b": 42}}', [".a.b"])
    assert out == "42\n"


def test_cli_index_access():
    code, out, err = run_main("[10, 20, 30]", [".[1]"])
    assert out == "20\n"


def test_cli_missing_query_is_usage_error():
    # A missing query is a usage error (exit 2), not an identity default.
    code, out, err = run_main('{"a": 1}', [])
    assert code == 2
    assert out == ""
    assert err.startswith("jqlite:")
    assert "query" in err


def test_cli_field_on_non_object_exits_5():
    code, out, err = run_main("1", [".a"])
    assert code == 5
    assert out == ""
    assert err == (
        "jqlite: field access '.a' requires an object, "
        "but the value is a number (1)\n"
    )


def test_cli_index_on_non_array_exits_5():
    code, out, err = run_main('"hello"', [".[0]"])
    assert code == 5
    assert out == ""
    assert "index access '[0]'" in err
    assert "string" in err


def test_cli_invalid_query_exits_5():
    code, out, err = run_main('{"a": 1}', [".["])
    assert code == 5
    assert out == ""
    assert err.startswith("jqlite:")


def test_cli_field_pretty_prints_object_result():
    code, out, err = run_main('{"a": {"x": 1, "y": 2}}', [".a"])
    assert code == 0
    assert out == '{\n  "x": 1,\n  "y": 2\n}\n'


# --------------------------------------------------------------------------- #
# module entrypoint
# --------------------------------------------------------------------------- #


def test_module_entrypoint_field_access():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", ".a"],
        input='{"a": {"b": 1}}',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == '{\n  "b": 1\n}\n'
    assert proc.stderr == ""


def test_module_entrypoint_type_error_exits_5():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", ".a"],
        input="42",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 5
    assert proc.stdout == ""
    assert "field access '.a'" in proc.stderr
