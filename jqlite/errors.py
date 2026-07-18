"""Error types for jqlite, each carrying the process exit code it maps to.

The v1 exit-code scheme:

* ``0`` — success.
* ``2`` — CLI/usage error: a bad flag or an unexpected extra argument
  (:class:`UsageError`).
* ``4`` — JSON parse error: malformed input on stdin (:class:`ParseError`).
* ``5`` — query or type error: a malformed query, or an operation applied to a
  value of the wrong type (:class:`QueryError`).

Every error message is written to stderr; the exit code is read off the raised
error's ``exit_code``.
"""

from __future__ import annotations

#: Exit status for a CLI/usage error (an unknown flag or an unexpected extra
#: positional argument).
EXIT_USAGE = 2

#: Exit status for a JSON parse error (malformed JSON on stdin).
EXIT_PARSE = 4

#: Exit status for a query or type error (malformed query, or an operation
#: applied to a value of the wrong type).
EXIT_QUERY = 5


class JqliteError(Exception):
    """Base class for jqlite errors.

    ``exit_code`` is the process exit status the error maps to.
    """

    exit_code: int = 1


class UsageError(JqliteError):
    """A CLI/usage error.

    Raised when invocation arguments are wrong: an unknown flag, or an
    unexpected extra positional argument. Maps to exit code 2.
    """

    exit_code = EXIT_USAGE


class ParseError(JqliteError):
    """A JSON parse error.

    Raised when the input read from stdin is not well-formed JSON. Maps to exit
    code 4.
    """

    exit_code = EXIT_PARSE


class QueryError(JqliteError):
    """A query or type error.

    Raised when a query is malformed, or when an access operation is applied to
    a value of the wrong type (e.g. field access on a non-object, or indexing a
    non-array). Maps to exit code 5.
    """

    exit_code = EXIT_QUERY
