"""Tests for exit code 2 (usage error): the command-line arguments are missing
or invalid.

A usage error is a problem with *how the command was invoked* — distinct from a
CSV parse error (exit 4, malformed input on stdin) and a query error (exit 5,
the columns/predicate reference something that does not exist). This module
pins the full exit-2 surface:

* a missing positional column argument;
* an empty (``""`` / whitespace-only) column argument, and one containing an
  empty selector (leading/trailing/doubled comma);
* an unknown flag;
* a ``--where`` flag missing its argument;
* an unexpected extra positional argument.

Each case asserts the code is exit 2, that nothing was written to stdout, and
that a ``csvlite:``-prefixed message was written to stderr.
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from csvlite.cli import main
from csvlite.errors import EXIT_PARSE, EXIT_QUERY, EXIT_USAGE

REPO_ROOT = Path(__file__).resolve().parents[2]

# A valid input used by cases where stdin content is irrelevant: the usage
# error is detected from argv before stdin is consulted.
SAMPLE = "name,age,city\nAda,36,London\nGrace,40,NYC\n"


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _assert_usage(code, out, err):
    assert code == EXIT_USAGE
    assert out == ""
    assert err.startswith("csvlite:")
    assert err.endswith("\n")


# --- missing argument --------------------------------------------------------


def test_no_arguments_is_usage_error():
    _assert_usage(*run_main(SAMPLE, []))


def test_only_flags_no_positional_is_usage_error():
    # --where present but no column argument at all.
    _assert_usage(*run_main(SAMPLE, ["--where", "age == 36"]))


def test_only_json_flag_no_positional_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["--json"]))


# --- empty / malformed column argument ---------------------------------------


def test_empty_string_column_argument_is_usage_error():
    _assert_usage(*run_main(SAMPLE, [""]))


def test_whitespace_only_column_argument_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["   "]))


def test_trailing_comma_selector_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["name,"]))


def test_leading_comma_selector_is_usage_error():
    _assert_usage(*run_main(SAMPLE, [",name"]))


def test_doubled_comma_selector_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["name,,age"]))


def test_bare_comma_argument_is_usage_error():
    _assert_usage(*run_main(SAMPLE, [","]))


def test_whitespace_selector_among_valid_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["name, ,age"]))


# --- unknown flag ------------------------------------------------------------


def test_unknown_long_flag_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["--nope", "name"]))


def test_unknown_short_flag_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["-x", "name"]))


def test_unknown_flag_after_positional_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["name", "--bogus"]))


# --- flag missing its argument -----------------------------------------------


def test_where_without_argument_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["name", "--where"]))


def test_where_as_final_token_is_usage_error():
    # --where is the very last token, so it cannot consume an argument.
    _assert_usage(*run_main(SAMPLE, ["--where"]))


# --- extra positional argument -----------------------------------------------


def test_two_positionals_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["name", "age"]))


def test_three_positionals_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["name", "age", "city"]))


def test_extra_positional_with_where_is_usage_error():
    _assert_usage(*run_main(SAMPLE, ["name", "extra", "--where", "age == 36"]))


# --- usage error precedes data/query errors ----------------------------------


def test_usage_error_detected_before_stdin_parse_error():
    # The stdin would be a parse error on its own, but the missing argument is
    # a usage error and is reported first (argv is validated before stdin).
    huge = "x" * (200_000)
    code, out, err = run_main(f"a\n{huge}\n", [])
    assert code == EXIT_USAGE
    assert code != EXIT_PARSE


def test_usage_error_takes_precedence_over_query_error():
    # An empty selector (usage) is reported even though the would-be lookup
    # could also be framed as an unknown column (query).
    code, out, err = run_main(SAMPLE, ["name,"])
    assert code == EXIT_USAGE
    assert code != EXIT_QUERY


# --- a single valid selector is NOT a usage error ----------------------------


def test_valid_single_column_is_not_usage_error():
    code, out, err = run_main(SAMPLE, ["name"])
    assert code == 0


def test_valid_index_selector_is_not_usage_error():
    code, out, err = run_main(SAMPLE, ["1"])
    assert code == 0


# --- end-to-end via the module entry point -----------------------------------


def test_module_entrypoint_missing_argument_exit_two():
    proc = subprocess.run(
        [sys.executable, "-m", "csvlite"],
        input=SAMPLE,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == EXIT_USAGE
    assert proc.stdout == ""
    assert proc.stderr.startswith("csvlite:")


def test_module_entrypoint_unknown_flag_exit_two():
    proc = subprocess.run(
        [sys.executable, "-m", "csvlite", "--nope", "name"],
        input=SAMPLE,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == EXIT_USAGE
    assert proc.stdout == ""
    assert proc.stderr.startswith("csvlite:")
