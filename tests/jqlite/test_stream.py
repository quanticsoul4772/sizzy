"""Tests for streaming stdin: multiple whitespace/NDJSON-separated JSON values.

jqlite reads a *stream* of top-level JSON values from stdin, runs the query on
each value independently, and emits all of one value's result(s) before moving
to the next — preserving input order.

The query argument is required (a missing query is a usage error, exit 2), so
streaming tests that exercise identity pass the explicit identity query ``.``.
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jqlite.cli import iter_json_values, main

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


# --- iter_json_values -------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", []),
        ("   \n\t  ", []),
        ("42", [42]),
        ("1 2 3", [1, 2, 3]),
        ("1\n2\n3", [1, 2, 3]),
        ('{"a": 1}\n{"b": 2}', [{"a": 1}, {"b": 2}]),
        ('{"a":1}{"b":2}', [{"a": 1}, {"b": 2}]),  # adjacent, no separator
        ('  {"a": 1}  \n\n  [1, 2]  ', [{"a": 1}, [1, 2]]),
        ('"x" "y"', ["x", "y"]),
        ("true false null", [True, False, None]),
    ],
)
def test_iter_json_values(text, expected):
    assert list(iter_json_values(text)) == expected


def test_iter_json_values_is_lazy():
    # A malformed value mid-stream only raises once it is reached, after the
    # earlier valid values have been yielded.
    gen = iter_json_values("1 2 not-json")
    assert next(gen) == 1
    assert next(gen) == 2
    with pytest.raises(json.JSONDecodeError):
        next(gen)


# --- streaming through main() ----------------------------------------------


def test_single_value_still_works():
    code, out, err = run_main('{"a": 1}', ["."])
    assert code == 0
    assert err == ""
    assert out == '{\n  "a": 1\n}\n'


def test_ndjson_each_value_processed_in_order():
    code, out, err = run_main('{"a": 1}\n{"a": 2}\n{"a": 3}', ['.a'])
    assert code == 0
    assert err == ""
    assert out == "1\n2\n3\n"


def test_whitespace_separated_values():
    code, out, err = run_main("1 2 3", ["."])
    assert code == 0
    assert out == "1\n2\n3\n"


def test_blank_lines_between_values_are_skipped():
    code, out, err = run_main('\n\n{"a": 1}\n\n\n{"a": 2}\n\n', ["."])
    assert code == 0
    assert out == '{\n  "a": 1\n}\n{\n  "a": 2\n}\n'


def test_empty_input_yields_no_output():
    code, out, err = run_main("", ["."])
    assert code == 0
    assert out == ""
    assert err == ""


def test_whitespace_only_input_yields_no_output():
    code, out, err = run_main("   \n\t ", ["."])
    assert code == 0
    assert out == ""
    assert err == ""


def test_iteration_query_spans_inputs_in_order():
    # Each input value's iteration results are emitted before the next input.
    code, out, err = run_main("[1, 2]\n[3, 4]", ['.[]'])
    assert code == 0
    assert out == "1\n2\n3\n4\n"


def test_select_filter_across_stream():
    code, out, err = run_main(
        '{"keep": true}\n{"keep": false}\n{"keep": true}', ['select(.keep)']
    )
    assert code == 0
    # Two of the three inputs survive the filter, in input order.
    assert out == (
        '{\n  "keep": true\n}\n'
        '{\n  "keep": true\n}\n'
    )


def test_query_error_after_emitting_earlier_results():
    # The first value succeeds and is emitted; the second is a type error for
    # field access, which aborts with exit 5 but keeps the earlier output.
    code, out, err = run_main('{"a": 1}\n42', ['.a'])
    assert code == 5
    assert out == "1\n"
    assert "jqlite:" in err


def test_query_error_emits_nothing_when_first_value_fails():
    code, out, err = run_main('42\n{"a": 1}', ['.a'])
    assert code == 5
    assert out == ""
    assert "jqlite:" in err


def test_stream_via_module_entrypoint():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", ".a"],
        input='{"a": 1}\n{"a": 2}',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0
    assert proc.stdout == "1\n2\n"
    assert proc.stderr == ""
