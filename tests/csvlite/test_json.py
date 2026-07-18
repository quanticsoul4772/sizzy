"""Tests for the ``--json`` flag: emit a JSON array of objects keyed by the
selected header names instead of CSV, exiting 0.
"""

import io
import json
import subprocess
import sys
from pathlib import Path

from csvlite.cli import main
from csvlite.errors import EXIT_QUERY, EXIT_USAGE

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_json_array_of_objects_keyed_by_selected_headers():
    code, out, err = run_main(
        "name,age,city\nAda,36,London\nGrace,40,NYC\n", ["name,age", "--json"]
    )
    assert code == 0
    assert err == ""
    assert json.loads(out) == [
        {"name": "Ada", "age": "36"},
        {"name": "Grace", "age": "40"},
    ]


def test_json_output_ends_with_newline():
    code, out, err = run_main("a,b\n1,2\n", ["a,b", "--json"])
    assert code == 0
    assert out.endswith("\n")


def test_json_key_order_follows_selection_order():
    code, out, err = run_main(
        "name,age,city\nAda,36,London\n", ["city,name", "--json"]
    )
    assert code == 0
    # The object key order must follow the selected order (city before name).
    assert out.strip() == json.dumps(
        [{"city": "London", "name": "Ada"}], ensure_ascii=False
    )
    assert list(json.loads(out)[0].keys()) == ["city", "name"]


def test_json_header_only_input_emits_empty_array():
    code, out, err = run_main("name,age\n", ["name", "--json"])
    assert code == 0
    assert json.loads(out) == []


def test_json_empty_stdin_unknown_column_is_query_error():
    code, out, err = run_main("", ["name", "--json"])
    assert code == EXIT_QUERY
    assert out == ""


def test_json_values_are_strings():
    code, out, err = run_main("n\n36\n", ["n", "--json"])
    assert code == 0
    record = json.loads(out)[0]
    assert record == {"n": "36"}
    assert isinstance(record["n"], str)


def test_json_composes_with_where():
    code, out, err = run_main(
        "name,age\nAda,36\nGrace,40\n", ["name", "--json", "--where", "age > 36"]
    )
    assert code == 0
    assert json.loads(out) == [{"name": "Grace"}]


def test_json_where_filters_all_rows_yields_empty_array():
    code, out, err = run_main(
        "name,age\nAda,36\n", ["name", "--json", "--where", "age > 100"]
    )
    assert code == 0
    assert json.loads(out) == []


def test_json_short_row_yields_empty_string_values():
    code, out, err = run_main("a,b,c\n1\n", ["b,c", "--json"])
    assert code == 0
    assert json.loads(out) == [{"b": "", "c": ""}]


def test_json_preserves_embedded_comma_value():
    code, out, err = run_main(
        'name,note\nAda,"hello, world"\n', ["note,name", "--json"]
    )
    assert code == 0
    assert json.loads(out) == [{"note": "hello, world", "name": "Ada"}]


def test_json_preserves_unicode_value():
    code, out, err = run_main("city\nMünchen\n", ["city", "--json"])
    assert code == 0
    assert json.loads(out) == [{"city": "München"}]


def test_json_index_selection():
    code, out, err = run_main(
        "name,age,city\nAda,36,London\n", ["1,3", "--json"]
    )
    assert code == 0
    assert json.loads(out) == [{"name": "Ada", "city": "London"}]


def test_json_unknown_column_is_query_error():
    code, out, err = run_main("name,age\nAda,36\n", ["name,nope", "--json"])
    assert code == EXIT_QUERY
    assert out == ""
    assert err.startswith("csvlite:")


def test_json_missing_column_argument_is_usage_error():
    code, out, err = run_main("a,b\n1,2\n", ["--json"])
    assert code == EXIT_USAGE
    assert out == ""


def test_json_flag_before_positional():
    code, out, err = run_main("a,b\n1,2\n", ["--json", "a"])
    assert code == 0
    assert json.loads(out) == [{"a": "1"}]


def test_json_module_entrypoint_exit_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "csvlite", "name,age", "--json"],
        input="name,age,city\nAda,36,London\n",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == [{"name": "Ada", "age": "36"}]
    assert proc.stderr == ""
