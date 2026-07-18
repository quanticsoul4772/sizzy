"""Tests for iteration ``.[]`` — emit each array element / object value.

Covers the parser (``Iterate`` step), the streaming evaluator
(:func:`evaluate_stream`), and the CLI: each result is emitted as its own
pretty-printed JSON value in input order, an empty collection emits nothing,
and iterating a scalar is a type error (exit 5).
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from jqlite.cli import main
from jqlite.errors import QueryError
from jqlite.eval import evaluate, evaluate_stream
from jqlite.parser import Field, Index, Iterate, parse_query

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


def test_parse_iterate():
    assert parse_query(".[]") == [Iterate()]


def test_parse_field_then_iterate():
    assert parse_query(".a[]") == [Field("a"), Iterate()]


def test_parse_field_dot_then_iterate():
    assert parse_query(".a.[]") == [Field("a"), Iterate()]


def test_parse_iterate_then_field():
    assert parse_query(".[].a") == [Iterate(), Field("a")]


def test_parse_iterate_then_index():
    assert parse_query(".[][0]") == [Iterate(), Index(0)]


def test_parse_index_then_iterate():
    assert parse_query(".[0][]") == [Index(0), Iterate()]


def test_parse_nested_iterate():
    assert parse_query(".[][]") == [Iterate(), Iterate()]


def test_parse_iterate_with_internal_whitespace():
    # Brackets with only whitespace inside are still iteration.
    assert parse_query(".[ ]") == [Iterate()]


# --------------------------------------------------------------------------- #
# evaluate_stream — success
# --------------------------------------------------------------------------- #


def test_iterate_array_elements_in_order():
    assert evaluate_stream([1, 2, 3], parse_query(".[]")) == [1, 2, 3]


def test_iterate_object_values_in_input_order():
    assert evaluate_stream({"a": 1, "b": 2, "c": 3}, parse_query(".[]")) == [1, 2, 3]


def test_iterate_object_preserves_non_sorted_order():
    # Keys are not sorted: values come out in the order the object was written.
    assert evaluate_stream({"z": 1, "a": 2}, parse_query(".[]")) == [1, 2]


def test_iterate_empty_array_yields_nothing():
    assert evaluate_stream([], parse_query(".[]")) == []


def test_iterate_empty_object_yields_nothing():
    assert evaluate_stream({}, parse_query(".[]")) == []


def test_iterate_single_element():
    assert evaluate_stream([42], parse_query(".[]")) == [42]


def test_iterate_preserves_element_types():
    src = [1, "two", True, None, [3], {"k": "v"}]
    assert evaluate_stream(src, parse_query(".[]")) == [1, "two", True, None, [3], {"k": "v"}]


def test_iterate_then_field():
    src = [{"a": 1}, {"a": 2}, {"a": 3}]
    assert evaluate_stream(src, parse_query(".[].a")) == [1, 2, 3]


def test_iterate_then_missing_field_is_null():
    src = [{"a": 1}, {"b": 2}]
    assert evaluate_stream(src, parse_query(".[].a")) == [1, None]


def test_iterate_then_index():
    src = [[10, 11], [20, 21]]
    assert evaluate_stream(src, parse_query(".[][0]")) == [10, 20]


def test_field_then_iterate():
    assert evaluate_stream({"items": [1, 2, 3]}, parse_query(".items[]")) == [1, 2, 3]


def test_index_then_iterate():
    assert evaluate_stream([[1, 2], [3, 4]], parse_query(".[0][]")) == [1, 2]


def test_nested_iterate_flattens_in_order():
    assert evaluate_stream([[1, 2], [3], [4, 5]], parse_query(".[][]")) == [1, 2, 3, 4, 5]


def test_iterate_then_iterate_over_objects():
    src = [{"x": 1, "y": 2}, {"z": 3}]
    assert evaluate_stream(src, parse_query(".[][]")) == [1, 2, 3]


# --------------------------------------------------------------------------- #
# evaluate_stream — type errors
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,typename",
    [
        (1, "number"),
        (3.5, "number"),
        ("hi", "string"),
        (True, "boolean"),
        (None, "null"),
    ],
)
def test_iterate_on_scalar_raises(value, typename):
    with pytest.raises(QueryError) as excinfo:
        evaluate_stream(value, parse_query(".[]"))
    msg = str(excinfo.value)
    assert "iteration '[]'" in msg
    assert typename in msg


def test_iterate_error_names_operation_type_and_value():
    with pytest.raises(QueryError) as excinfo:
        evaluate_stream(7, parse_query(".[]"))
    assert str(excinfo.value) == (
        "iteration '[]' requires an array or object, "
        "but the value is a number (7)"
    )


def test_iterate_error_surfaces_mid_stream():
    # The second element is a scalar; iterating it fails the whole query.
    with pytest.raises(QueryError):
        evaluate_stream([[1], 2], parse_query(".[][]"))


# --------------------------------------------------------------------------- #
# evaluate (single-result convenience) over a non-iterating query is unchanged
# --------------------------------------------------------------------------- #


def test_evaluate_single_result_still_works():
    assert evaluate({"a": 1}, parse_query(".a")) == 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_iterate_array_emits_each_result():
    code, out, err = run_main("[1, 2, 3]", [".[]"])
    assert code == 0
    assert err == ""
    assert out == "1\n2\n3\n"


def test_cli_iterate_object_emits_values_in_order():
    code, out, err = run_main('{"a": 1, "b": 2}', [".[]"])
    assert code == 0
    assert out == "1\n2\n"


def test_cli_iterate_empty_array_emits_nothing():
    code, out, err = run_main("[]", [".[]"])
    assert code == 0
    assert out == ""
    assert err == ""


def test_cli_iterate_empty_object_emits_nothing():
    code, out, err = run_main("{}", [".[]"])
    assert code == 0
    assert out == ""


def test_cli_iterate_then_field():
    code, out, err = run_main('[{"x": 1}, {"x": 2}]', [".[].x"])
    assert code == 0
    assert out == "1\n2\n"


def test_cli_iterate_pretty_prints_each_object_result():
    code, out, err = run_main('[{"a": 1}, {"b": 2}]', [".[]"])
    assert code == 0
    assert out == (
        "{\n"
        '  "a": 1\n'
        "}\n"
        "{\n"
        '  "b": 2\n'
        "}\n"
    )


def test_cli_iterate_on_scalar_exits_5():
    code, out, err = run_main("42", [".[]"])
    assert code == 5
    assert out == ""
    assert "iteration '[]'" in err
    assert "number" in err


def test_cli_field_then_iterate():
    code, out, err = run_main('{"items": [10, 20]}', [".items[]"])
    assert code == 0
    assert out == "10\n20\n"


# --------------------------------------------------------------------------- #
# module entrypoint
# --------------------------------------------------------------------------- #


def test_module_entrypoint_iterate():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", ".[]"],
        input="[1, 2, 3]",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == "1\n2\n3\n"
    assert proc.stderr == ""


def test_module_entrypoint_iterate_scalar_exits_5():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", ".[]"],
        input='"nope"',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 5
    assert proc.stdout == ""
    assert "iteration '[]'" in proc.stderr
