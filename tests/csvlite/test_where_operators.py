"""Tests for the six ``--where`` comparison operators ``== != < <= > >=``.

Covers, for each operator: numeric comparison when both operands parse as
numbers, string comparison otherwise, the parser splitting at the correct
operator (two-character forms preferred over one-character), filtering through
``main`` (exit 0), and the operator-level helper :func:`compare_cell`. The
``==`` operator's deeper semantics live in ``test_where.py``; this file focuses
on the five operators added here and the cross-cutting numeric/string rule.
"""

import io

import pytest

from csvlite.cli import OPERATORS, compare_cell, main, parse_predicate
from csvlite.errors import QueryError


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


# --- the operator set --------------------------------------------------------


def test_all_six_operators_are_supported():
    assert set(OPERATORS) == {"==", "!=", "<", "<=", ">", ">="}


# --- parse_predicate splits at the right operator ----------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("age == 36", ("age", "==", "36")),
        ("age != 36", ("age", "!=", "36")),
        ("age < 36", ("age", "<", "36")),
        ("age <= 36", ("age", "<=", "36")),
        ("age > 36", ("age", ">", "36")),
        ("age >= 36", ("age", ">=", "36")),
    ],
)
def test_parse_predicate_each_operator(text, expected):
    assert parse_predicate(text) == expected


def test_parse_predicate_no_space_each_operator():
    assert parse_predicate("age!=36") == ("age", "!=", "36")
    assert parse_predicate("age<36") == ("age", "<", "36")
    assert parse_predicate("age<=36") == ("age", "<=", "36")
    assert parse_predicate("age>36") == ("age", ">", "36")
    assert parse_predicate("age>=36") == ("age", ">=", "36")


def test_parse_predicate_prefers_two_char_over_one_char():
    # '<=' must not be read as a lone '<' with value '=36'.
    assert parse_predicate("age <= 36") == ("age", "<=", "36")
    assert parse_predicate("age >= 36") == ("age", ">=", "36")


def test_parse_predicate_single_equals_is_malformed():
    # A bare '=' is not an operator; only '==' is.
    with pytest.raises(QueryError):
        parse_predicate("age = 36")


def test_parse_predicate_empty_column_for_lt_raises():
    with pytest.raises(QueryError):
        parse_predicate("< 36")


# --- compare_cell numeric semantics ------------------------------------------


@pytest.mark.parametrize(
    "cell,op,value,expected",
    [
        ("36", "==", "36", True),
        ("36", "!=", "37", True),
        ("36", "!=", "36", False),
        ("5", "<", "10", True),
        ("10", "<", "5", False),
        ("5", "<=", "5", True),
        ("6", "<=", "5", False),
        ("10", ">", "5", True),
        ("5", ">", "10", False),
        ("5", ">=", "5", True),
        ("4", ">=", "5", False),
    ],
)
def test_compare_cell_numeric(cell, op, value, expected):
    assert compare_cell(cell, op, value) is expected


def test_compare_cell_numeric_int_float_spelling():
    # Both parse as numbers => numeric ordering, not lexical.
    assert compare_cell("9", "<", "10") is True
    assert compare_cell("9", "<", "10.0") is True
    assert compare_cell("100", ">", "99.5") is True


def test_compare_cell_numeric_beats_lexical():
    # Numerically 9 < 100, even though lexically "9" > "100".
    assert compare_cell("9", "<", "100") is True
    assert compare_cell("9", ">", "100") is False


def test_compare_cell_numeric_negative():
    assert compare_cell("-5", "<", "0") is True
    assert compare_cell("-5", ">", "-10") is True


# --- compare_cell string semantics -------------------------------------------


@pytest.mark.parametrize(
    "cell,op,value,expected",
    [
        ("London", "==", "London", True),
        ("London", "!=", "Paris", True),
        ("Ada", "<", "Bob", True),
        ("Bob", "<", "Ada", False),
        ("Ada", "<=", "Ada", True),
        ("Bob", ">", "Ada", True),
        ("Ada", ">=", "Ada", True),
    ],
)
def test_compare_cell_string(cell, op, value, expected):
    assert compare_cell(cell, op, value) is expected


def test_compare_cell_string_when_one_side_not_numeric():
    # Numeric-looking cell but non-numeric value => string comparison, so the
    # ordering is lexical rather than numeric.
    # "9" < "n/a" lexically (a digit precedes letters).
    assert compare_cell("9", "<", "n/a") is True
    # "9" > "10x" lexically ('9' > '1'), even though 9 < 10 numerically — the
    # non-numeric "10x" forces a string comparison.
    assert compare_cell("9", ">", "10x") is True


# --- filtering through main (exit 0) -----------------------------------------


def test_where_not_equal_filters_rows():
    code, out, err = run_main(
        "name,age\nAda,36\nGrace,40\nLinus,36\n",
        ["name", "--where", "age != 36"],
    )
    assert code == 0
    assert err == ""
    assert out == "name\nGrace\n"


def test_where_less_than_numeric():
    code, out, err = run_main(
        "name,age\nAda,36\nGrace,40\nLinus,21\n",
        ["name", "--where", "age < 36"],
    )
    assert code == 0
    assert out == "name\nLinus\n"


def test_where_less_equal_numeric():
    code, out, err = run_main(
        "name,age\nAda,36\nGrace,40\nLinus,21\n",
        ["name", "--where", "age <= 36"],
    )
    assert code == 0
    assert out == "name\nAda\nLinus\n"


def test_where_greater_than_numeric():
    code, out, err = run_main(
        "name,age\nAda,36\nGrace,40\nLinus,21\n",
        ["name", "--where", "age > 36"],
    )
    assert code == 0
    assert out == "name\nGrace\n"


def test_where_greater_equal_numeric():
    code, out, err = run_main(
        "name,age\nAda,36\nGrace,40\nLinus,21\n",
        ["name", "--where", "age >= 36"],
    )
    assert code == 0
    assert out == "name\nAda\nGrace\n"


def test_where_less_than_string():
    # Non-numeric cells => string ordering.
    code, out, err = run_main(
        "name,city\nAda,London\nGrace,NYC\nLinus,Berlin\n",
        ["name,city", "--where", "city < London"],
    )
    assert code == 0
    assert out == "name,city\nLinus,Berlin\n"


def test_where_greater_equal_string():
    code, out, err = run_main(
        "name,city\nAda,London\nGrace,NYC\nLinus,Berlin\n",
        ["city", "--where", "city >= London"],
    )
    assert code == 0
    assert out == "city\nLondon\nNYC\n"


def test_where_not_equal_string():
    code, out, err = run_main(
        "name,city\nAda,London\nGrace,NYC\n",
        ["name", "--where", "city != London"],
    )
    assert code == 0
    assert out == "name\nGrace\n"


def test_where_numeric_value_string_cell_uses_string_compare():
    # Cell "n/a" is not numeric, so even a numeric value compares as a string.
    code, out, err = run_main(
        "name,age\nAda,n/a\nGrace,40\n",
        ["name", "--where", "age > 5"],
    )
    assert code == 0
    # "n/a" > "5" lexically (letters > digits); "40" > "5" lexically too.
    assert out == "name\nAda\nGrace\n"


def test_where_each_operator_exits_zero():
    data = "name,age\nAda,36\nGrace,40\n"
    for op in ("==", "!=", "<", "<=", ">", ">="):
        code, _out, err = run_main(data, ["name", "--where", f"age {op} 36"])
        assert code == 0, f"operator {op} did not exit 0"
        assert err == ""


def test_where_operator_with_reorder_and_index():
    code, out, err = run_main(
        "name,age,city\nAda,36,London\nGrace,40,NYC\n",
        ["3,1", "--where", "age >= 40"],
    )
    assert code == 0
    assert out == "city,name\nNYC,Grace\n"
