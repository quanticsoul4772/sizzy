"""Tests for the optional ``--where 'COLUMN == VALUE'`` equality predicate.

Covers numeric-vs-string comparison semantics, the ``--where`` / ``--where=``
argument forms, filtering interacting with selection/reorder, and the error
cases (unknown predicate column = query error, missing predicate arg = usage
error, malformed predicate = query error). Only the ``==`` operator is in scope.
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from csvlite.cli import cell_matches, main, parse_predicate
from csvlite.errors import EXIT_QUERY, EXIT_USAGE, QueryError

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


# --- string equality ---------------------------------------------------------


def test_where_string_equality_filters_rows():
    code, out, err = run_main(
        "name,city\nAda,London\nGrace,NYC\nLinus,London\n",
        ["name,city", "--where", "city == London"],
    )
    assert code == 0
    assert err == ""
    assert out == "name,city\nAda,London\nLinus,London\n"


def test_where_string_no_match_emits_header_only():
    code, out, err = run_main(
        "name,city\nAda,London\n",
        ["name", "--where", "city == Paris"],
    )
    assert code == 0
    assert out == "name\n"


def test_where_string_is_not_numeric_coerced():
    # "London" is not a number, so a string compare is used (and matches).
    code, out, err = run_main(
        "name,city\nAda,London\n",
        ["name", "--where", "city == London"],
    )
    assert code == 0
    assert out == "name\nAda\n"


# --- numeric equality --------------------------------------------------------


def test_where_numeric_equality_filters_rows():
    code, out, err = run_main(
        "name,age\nAda,36\nGrace,40\nLinus,36\n",
        ["name", "--where", "age == 36"],
    )
    assert code == 0
    assert out == "name\nAda\nLinus\n"


def test_where_numeric_matches_across_int_float_spelling():
    # Cell "36" and value "36.0" both parse as numbers => numeric equality.
    code, out, err = run_main(
        "name,age\nAda,36\n",
        ["name", "--where", "age == 36.0"],
    )
    assert code == 0
    assert out == "name\nAda\n"


def test_where_numeric_float_cell_matches_int_value():
    code, out, err = run_main(
        "name,score\nAda,36.0\n",
        ["name", "--where", "score == 36"],
    )
    assert code == 0
    assert out == "name\nAda\n"


def test_where_numeric_no_match():
    code, out, err = run_main(
        "name,age\nAda,36\n",
        ["name", "--where", "age == 99"],
    )
    assert code == 0
    assert out == "name\n"


def test_where_numeric_negative_value():
    code, out, err = run_main(
        "name,delta\nAda,-5\nGrace,5\n",
        ["name", "--where", "delta == -5"],
    )
    assert code == 0
    assert out == "name\nAda\n"


def test_where_mixed_numeric_and_string_cell_uses_string():
    # value "n/a" is not numeric, so even a numeric-looking cell compares as
    # a string; no row matches.
    code, out, err = run_main(
        "name,age\nAda,36\n",
        ["name", "--where", "age == n/a"],
    )
    assert code == 0
    assert out == "name\n"


# --- empty value matches empty cells ----------------------------------------


def test_where_empty_value_matches_empty_cell():
    code, out, err = run_main(
        "name,note\nAda,\nGrace,hi\n",
        ["name", "--where", "note =="],
    )
    assert code == 0
    assert out == "name\nAda\n"


def test_where_short_row_treats_missing_cell_as_empty():
    # The data row has no 'note' field; it is treated as empty and matches "".
    code, out, err = run_main(
        "name,note\nAda\n",
        ["name", "--where", "note =="],
    )
    assert code == 0
    assert out == "name\nAda\n"


# --- argument forms and interaction -----------------------------------------


def test_where_equals_form():
    code, out, err = run_main(
        "name,city\nAda,London\nGrace,NYC\n",
        ["name", "--where=city == London"],
    )
    assert code == 0
    assert out == "name\nAda\n"


def test_where_before_positional():
    code, out, err = run_main(
        "name,city\nAda,London\nGrace,NYC\n",
        ["--where", "city == NYC", "name"],
    )
    assert code == 0
    assert out == "name\nGrace\n"


def test_where_column_need_not_be_selected():
    # Filter on 'age' but only project 'name'.
    code, out, err = run_main(
        "name,age,city\nAda,36,London\nGrace,40,NYC\n",
        ["name,city", "--where", "age == 40"],
    )
    assert code == 0
    assert out == "name,city\nGrace,NYC\n"


def test_where_with_reorder_and_index_selection():
    code, out, err = run_main(
        "name,age,city\nAda,36,London\nGrace,40,NYC\n",
        ["3,1", "--where", "age == 36"],
    )
    assert code == 0
    assert out == "city,name\nLondon,Ada\n"


def test_no_where_keeps_all_rows():
    code, out, err = run_main(
        "name,age\nAda,36\nGrace,40\n",
        ["name"],
    )
    assert code == 0
    assert out == "name\nAda\nGrace\n"


# --- error cases -------------------------------------------------------------


def test_where_unknown_column_is_query_error():
    code, out, err = run_main(
        "name,age\nAda,36\n",
        ["name", "--where", "nope == 1"],
    )
    assert code == EXIT_QUERY
    assert out == ""
    assert err.startswith("csvlite:")
    assert "nope" in err


def test_where_missing_argument_is_usage_error():
    code, out, err = run_main(
        "name,age\nAda,36\n",
        ["name", "--where"],
    )
    assert code == EXIT_USAGE
    assert out == ""
    assert err.startswith("csvlite:")


def test_where_malformed_no_operator_is_query_error():
    code, out, err = run_main(
        "name,age\nAda,36\n",
        ["name", "--where", "age 36"],
    )
    assert code == EXIT_QUERY
    assert out == ""
    assert err.startswith("csvlite:")


def test_where_malformed_empty_column_is_query_error():
    code, out, err = run_main(
        "name,age\nAda,36\n",
        ["name", "--where", "== 36"],
    )
    assert code == EXIT_QUERY
    assert out == ""


# --- unit-level helpers ------------------------------------------------------


def test_parse_predicate_basic():
    assert parse_predicate("age == 36") == ("age", "==", "36")


def test_parse_predicate_strips_whitespace():
    assert parse_predicate("  city  ==  New York ") == ("city", "==", "New York")


def test_parse_predicate_no_space():
    assert parse_predicate("age==36") == ("age", "==", "36")


def test_parse_predicate_empty_value():
    assert parse_predicate("note ==") == ("note", "==", "")


def test_parse_predicate_no_operator_raises():
    with pytest.raises(QueryError):
        parse_predicate("age 36")


def test_parse_predicate_empty_column_raises():
    with pytest.raises(QueryError):
        parse_predicate("== 36")


def test_cell_matches_numeric():
    assert cell_matches("36", "36.0") is True
    assert cell_matches("36", "37") is False


def test_cell_matches_string():
    assert cell_matches("London", "London") is True
    assert cell_matches("London", "Paris") is False


def test_cell_matches_string_when_value_not_numeric():
    # Numeric-looking cell, non-numeric value => string compare.
    assert cell_matches("36", "thirty-six") is False


def test_module_entrypoint_where_exit_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "csvlite", "name", "--where", "city == London"],
        input="name,city\nAda,London\nGrace,NYC\n",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == "name\nAda\n"
    assert proc.stderr == ""
