"""Tests for rejection of constructs outside the jqlite v1 surface.

v1 supports only: identity ``.``, field/index access, iteration ``.[]``, the
``select(f)`` / ``map(f)`` filters, and the builtins ``keys`` / ``length`` /
``type`` / ``has(k)``. Anything else — pipes, arithmetic, comparison/boolean
operators, assignment/update, string interpolation, recursive descent ``..``,
and any unknown filter or builtin name — must be a *query* error: a
:class:`QueryError` (exit 5) whose stderr message names the unsupported
construct, never a parse (4) or usage (2) error.
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from jqlite.cli import main
from jqlite.errors import EXIT_QUERY, QueryError
from jqlite.parser import parse_query

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_main(input_text, argv=None):
    """Invoke main() with injected string IO; return (code, stdout, stderr)."""
    stdin = io.StringIO(input_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv or [], stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


# --------------------------------------------------------------------------- #
# parser — each out-of-scope construct raises QueryError naming the construct
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "query,needle",
    [
        # pipes
        (".a | .b", "pipe operator '|'"),
        (".a|.b", "pipe operator '|'"),
        ("| .a", "pipe operator '|'"),
        # arithmetic
        (".a + 1", "arithmetic operator '+'"),
        (".a+1", "arithmetic operator '+'"),
        (".a - .b", "arithmetic operator '-'"),
        (".a * 2", "arithmetic operator '*'"),
        (".a / 2", "arithmetic operator '/'"),
        (".a % 2", "arithmetic operator '%'"),
        # comparison / boolean
        (".a == 1", "comparison operator '=='"),
        (".a != 1", "comparison operator '!='"),
        (".a < 1", "comparison operator '<'"),
        (".a > 1", "comparison operator '>'"),
        (".a <= 1", "comparison operator '<='"),
        (".a >= 1", "comparison operator '>='"),
        (".a and .b", "boolean operator 'and'"),
        (".a or .b", "boolean operator 'or'"),
        ("and .b", "boolean operator 'and'"),
        ("not", "boolean operator 'not'"),
        ("not(.a)", "boolean operator 'not'"),
        # assignment / update
        (".a = 1", "assignment operator '='"),
        (".a |= .b", "update-assignment operator '|='"),
        (".a += 1", "update-assignment operator '+='"),
        # string interpolation
        ("\\(.a)", "string interpolation"),
        # recursive descent
        ("..", "recursive descent '..'"),
        (".a..b", "recursive descent '..'"),
        # unknown names (filters / builtins not in the v1 set)
        ("floor", "not a supported filter or builtin"),
        ("tostring", "not a supported filter or builtin"),
        ("nope(.a)", "not a supported filter or builtin"),
        ("Select(.a)", "not a supported filter or builtin"),
    ],
)
def test_out_of_scope_construct_raises_named_query_error(query, needle):
    with pytest.raises(QueryError) as excinfo:
        parse_query(query)
    msg = str(excinfo.value)
    assert needle in msg
    # The query string itself is echoed so the user can locate the construct.
    assert repr(query.strip()) in msg or query.strip() in msg


def test_unsupported_message_mentions_v1_boundary():
    with pytest.raises(QueryError) as excinfo:
        parse_query(".a | .b")
    assert "jqlite v1" in str(excinfo.value)


def test_unknown_builtin_names_the_offending_name():
    with pytest.raises(QueryError) as excinfo:
        parse_query("floor")
    assert "'floor'" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# in-scope queries still parse (the rejection does not over-reach)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "query",
    [
        ".",
        ".a",
        ".a.b",
        ".[0]",
        ".[-1]",
        ".[]",
        ".a[0]",
        "select(.a)",
        "map(.a)",
        "keys",
        "length",
        "type",
        'has("k")',
        "has(-1)",
        "map(select(.a))",
    ],
)
def test_in_scope_queries_are_not_rejected(query):
    # Should not raise — these are the v1 surface.
    parse_query(query)


# --------------------------------------------------------------------------- #
# CLI — out-of-scope queries exit 5 with the construct on stderr
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "query,needle",
    [
        (".a | .b", "pipe operator '|'"),
        (".a + 1", "arithmetic operator '+'"),
        (".a == 1", "comparison operator '=='"),
        (".a and .b", "boolean operator 'and'"),
        (".a = 1", "assignment operator '='"),
        ("..", "recursive descent '..'"),
        ("floor", "not a supported filter or builtin"),
    ],
)
def test_cli_out_of_scope_exits_5_with_message(query, needle):
    code, out, err = run_main('{"a": 1, "b": 2}', [query])
    assert code == EXIT_QUERY
    assert code == 5
    assert out == ""
    assert err.startswith("jqlite:")
    assert needle in err


def test_cli_unsupported_is_query_error_not_parse_or_usage():
    # The input JSON is valid and the invocation is well-formed; only the query
    # is out of scope — so it is a query error (5), not 4 or 2.
    code, out, err = run_main('{"a": 1}', [".a | .b"])
    assert code == 5
    assert "invalid JSON" not in err
    assert "unknown option" not in err


# --------------------------------------------------------------------------- #
# module entrypoint — distinct exit 5 through the real process boundary
# --------------------------------------------------------------------------- #


def test_module_entrypoint_pipe_exits_5():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", ".a | .b"],
        input='{"a": 1}',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 5
    assert proc.stdout == ""
    assert "pipe operator '|'" in proc.stderr


def test_module_entrypoint_recursive_descent_exits_5():
    proc = subprocess.run(
        [sys.executable, "-m", "jqlite", ".."],
        input='{"a": 1}',
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 5
    assert proc.stdout == ""
    assert "recursive descent" in proc.stderr
