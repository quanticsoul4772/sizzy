"""Tests for the csvlite scaffold: read CSV from stdin (first row = header),
select/reorder columns by name, emit CSV, with the shared exit-code scheme.
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from csvlite.cli import main, select_columns
from csvlite.errors import EXIT_PARSE, EXIT_QUERY, EXIT_USAGE

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_select_subset_in_header_order():
    code, out, err = run_main(
        "name,age,city\nAda,36,London\nGrace,40,NYC\n", ["name,age"]
    )
    assert code == 0
    assert err == ""
    assert out == "name,age\nAda,36\nGrace,40\n"


def test_select_single_column():
    code, out, err = run_main("name,age\nAda,36\n", ["age"])
    assert code == 0
    assert out == "age\n36\n"


def test_reorder_columns():
    code, out, err = run_main("name,age,city\nAda,36,London\n", ["city,name"])
    assert code == 0
    assert out == "city,name\nLondon,Ada\n"


def test_all_columns_explicitly():
    code, out, err = run_main("a,b\n1,2\n3,4\n", ["a,b"])
    assert code == 0
    assert out == "a,b\n1,2\n3,4\n"


def test_header_only_input_emits_header():
    code, out, err = run_main("name,age\n", ["name"])
    assert code == 0
    assert out == "name\n"


def test_quoted_field_with_embedded_comma_preserved():
    code, out, err = run_main(
        'name,note\nAda,"hello, world"\n', ["note,name"]
    )
    assert code == 0
    # The embedded comma forces csv to re-quote the field on output.
    assert out == 'note,name\n"hello, world",Ada\n'


def test_quoted_field_with_embedded_newline():
    code, out, err = run_main('name,note\nAda,"a\nb"\n', ["note"])
    assert code == 0
    assert out == 'note\n"a\nb"\n'


def test_short_row_yields_empty_cells():
    # A data row with fewer fields than the header pads with empty strings.
    code, out, err = run_main("a,b,c\n1\n", ["b,c"])
    assert code == 0
    assert out == "b,c\n,\n"


def test_unknown_column_is_query_error():
    code, out, err = run_main("name,age\nAda,36\n", ["name,nope"])
    assert code == EXIT_QUERY
    assert out == ""
    assert "nope" in err
    assert err.startswith("csvlite:")


def test_missing_argument_is_usage_error():
    code, out, err = run_main("name,age\nAda,36\n", [])
    assert code == EXIT_USAGE
    assert out == ""
    assert err.startswith("csvlite:")


def test_extra_argument_is_usage_error():
    code, out, err = run_main("a,b\n1,2\n", ["a", "b"])
    assert code == EXIT_USAGE
    assert out == ""


def test_unknown_flag_is_usage_error():
    code, out, err = run_main("a,b\n1,2\n", ["--nope"])
    assert code == EXIT_USAGE
    assert out == ""


def test_empty_stdin_unknown_column_is_query_error():
    code, out, err = run_main("", ["name"])
    assert code == EXIT_QUERY
    assert out == ""


def test_duplicate_header_name_picks_first():
    indices, names = select_columns(["x", "x", "y"], "x,y")
    assert indices == [0, 2]
    assert names == ["x", "y"]


def test_select_columns_unknown_raises():
    from csvlite.errors import QueryError

    with pytest.raises(QueryError):
        select_columns(["a", "b"], "a,c")


def test_module_entrypoint_exit_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "csvlite", "name,age"],
        input="name,age,city\nAda,36,London\n",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == "name,age\nAda,36\n"
    assert proc.stderr == ""
