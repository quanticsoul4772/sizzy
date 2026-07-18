"""Tests for column selection by 1-based index in the positional argument.

Covers selecting and reordering columns via index (e.g. '1,3'), mixing names
and indices, the actual header names appearing on output, and out-of-range
indices being a query error (exit code 5).
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from csvlite.cli import select_columns
from csvlite.errors import EXIT_QUERY, QueryError

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    from csvlite.cli import main

    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_select_by_index_subset_and_reorder():
    code, out, err = run_main(
        "name,age,city\nAda,36,London\nGrace,40,NYC\n", ["1,3"]
    )
    assert code == 0
    assert err == ""
    # Index 1 -> name, index 3 -> city; output keyed by the real header names.
    assert out == "name,city\nAda,London\nGrace,NYC\n"


def test_select_by_index_reorders():
    code, out, err = run_main("name,age,city\nAda,36,London\n", ["3,1"])
    assert code == 0
    assert out == "city,name\nLondon,Ada\n"


def test_select_single_index():
    code, out, err = run_main("name,age\nAda,36\n", ["2"])
    assert code == 0
    assert out == "age\n36\n"


def test_select_all_by_index():
    code, out, err = run_main("a,b\n1,2\n3,4\n", ["1,2"])
    assert code == 0
    assert out == "a,b\n1,2\n3,4\n"


def test_repeated_index_duplicates_column():
    code, out, err = run_main("a,b\n1,2\n", ["1,1"])
    assert code == 0
    assert out == "a,a\n1,1\n"


def test_mixed_name_and_index():
    code, out, err = run_main(
        "name,age,city\nAda,36,London\n", ["name,3"]
    )
    assert code == 0
    assert out == "name,city\nAda,London\n"


def test_index_with_short_row_pads_empty():
    code, out, err = run_main("a,b,c\n1\n", ["2,3"])
    assert code == 0
    assert out == "b,c\n,\n"


def test_index_zero_is_query_error():
    code, out, err = run_main("name,age\nAda,36\n", ["0"])
    assert code == EXIT_QUERY
    assert out == ""
    assert err.startswith("csvlite:")
    assert "0" in err


def test_index_too_large_is_query_error():
    code, out, err = run_main("name,age\nAda,36\n", ["3"])
    assert code == EXIT_QUERY
    assert out == ""
    assert err.startswith("csvlite:")
    assert "3" in err


def test_index_out_of_range_among_valid_is_query_error():
    code, out, err = run_main("name,age\nAda,36\n", ["1,9"])
    assert code == EXIT_QUERY
    assert out == ""


def test_select_columns_index_resolution():
    indices, names = select_columns(["name", "age", "city"], "1,3")
    assert indices == [0, 2]
    assert names == ["name", "city"]


def test_select_columns_mixed_resolution():
    indices, names = select_columns(["name", "age", "city"], "age,1")
    assert indices == [1, 0]
    assert names == ["age", "name"]


def test_select_columns_out_of_range_raises():
    with pytest.raises(QueryError):
        select_columns(["a", "b"], "3")


def test_select_columns_index_zero_raises():
    with pytest.raises(QueryError):
        select_columns(["a", "b"], "0")


def test_numeric_token_prefers_index_over_name():
    # A header literally named "1" is shadowed by index resolution: token "1"
    # is the 1-based index, i.e. the first column.
    indices, names = select_columns(["1", "2"], "1")
    assert indices == [0]
    assert names == ["1"]


def test_module_entrypoint_index_exit_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "csvlite", "1,3"],
        input="name,age,city\nAda,36,London\n",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == "name,city\nAda,London\n"
    assert proc.stderr == ""
