"""Tests for the distinct exit-code scheme.

jqlite maps error categories to distinct, non-zero exit codes, with every error
message written to stderr (never stdout):

* 2 — CLI/usage error: a missing query, an unknown flag, or an unexpected extra
  argument.
* 4 — JSON parse error: malformed JSON on stdin.
* 5 — query/type error (owned by its own task; cross-checked here for the
  contract that the three codes stay distinct).

0 is success.
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from jqlite.cli import main
from jqlite.errors import (
    EXIT_PARSE,
    EXIT_QUERY,
    EXIT_USAGE,
    ParseError,
    QueryError,
    UsageError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


# --- error-type exit_code mapping ------------------------------------------


def test_error_codes_are_distinct():
    assert len({EXIT_USAGE, EXIT_PARSE, EXIT_QUERY}) == 3
    assert (EXIT_USAGE, EXIT_PARSE, EXIT_QUERY) == (2, 4, 5)


def test_error_classes_carry_their_exit_code():
    assert UsageError("x").exit_code == 2
    assert ParseError("x").exit_code == 4
    assert QueryError("x").exit_code == 5


# --- usage errors (exit 2) -------------------------------------------------


def test_missing_query_is_usage_error():
    code, out, err = run_main('{"a": 1}', [])
    assert code == EXIT_USAGE
    assert out == ""
    assert err.startswith("jqlite:")
    assert "query" in err


@pytest.mark.parametrize("flag", ["-x", "--bogus", "-Z", "--compactt"])
def test_unknown_flag_is_usage_error(flag):
    code, out, err = run_main('{"a": 1}', [flag])
    assert code == EXIT_USAGE
    assert out == ""
    assert err.startswith("jqlite:")
    assert "unknown option" in err
    assert flag in err


def test_unknown_flag_before_query():
    code, out, err = run_main('{"a": 1}', ["--nope", ".a"])
    assert code == EXIT_USAGE
    assert out == ""


def test_extra_positional_argument_is_usage_error():
    code, out, err = run_main('{"a": 1}', [".a", ".b"])
    assert code == EXIT_USAGE
    assert out == ""
    assert err.startswith("jqlite:")
    assert "extra argument" in err
    assert "'.b'" in err


def test_multiple_extra_arguments_listed():
    code, out, err = run_main("1", [".", "x", "y"])
    assert code == EXIT_USAGE
    assert "'x'" in err
    assert "'y'" in err


def test_compact_flag_is_not_a_usage_error():
    # The known flag must not be mistaken for an unknown option.
    code, out, err = run_main('{"a": 1}', ["-c", "."])
    assert code == 0
    assert err == ""
    assert out == '{"a":1}\n'


# --- JSON parse errors (exit 4) --------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "not-json",
        "{",
        "{'a': 1}",  # single quotes are not valid JSON
        "[1, 2,]",  # trailing comma
        "{\"a\": }",
        "tru",
    ],
)
def test_malformed_json_is_parse_error(bad):
    code, out, err = run_main(bad, ["."])
    assert code == EXIT_PARSE
    assert out == ""
    assert err.startswith("jqlite:")
    assert "invalid JSON on stdin" in err


def test_parse_error_retains_earlier_stream_output():
    # The first value is valid and emitted; the second is malformed -> exit 4
    # but the earlier output is kept.
    code, out, err = run_main('{"a": 1}\nnot-json', [".a"])
    assert code == EXIT_PARSE
    assert out == "1\n"
    assert "invalid JSON on stdin" in err


def test_parse_error_message_to_stderr_not_stdout():
    code, out, err = run_main("{", ["."])
    assert out == ""
    assert err != ""


# --- query/type errors stay at exit 5 (distinctness cross-check) -----------


def test_query_error_still_exit_five():
    # Field access on a non-object is a type error: code 5, distinct from 2/4.
    code, out, err = run_main("42", [".a"])
    assert code == EXIT_QUERY
    assert out == ""
    assert err.startswith("jqlite:")


def test_malformed_query_is_query_error_not_usage():
    # A query that begins with '.' but is malformed is a query error (5),
    # not a usage error (2): it is a query problem, not an invocation problem.
    code, out, err = run_main("1", [".."])
    assert code == EXIT_QUERY


# --- success path unaffected -----------------------------------------------


def test_success_is_exit_zero():
    code, out, err = run_main('{"a": 1}', [".a"])
    assert code == 0
    assert err == ""


# --- distinct codes through the real module entry point ---------------------


def test_module_entrypoint_usage_error_exit_two():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", "--bogus"],
        input='{"a": 1}',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == EXIT_USAGE
    assert proc.stdout == ""
    assert proc.stderr.startswith("jqlite:")


def test_module_entrypoint_parse_error_exit_four():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", "."],
        input="not-json",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == EXIT_PARSE
    assert proc.stdout == ""
    assert "invalid JSON on stdin" in proc.stderr
