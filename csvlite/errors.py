"""Error types for csvlite, each carrying the process exit code it maps to.

The v1 exit-code scheme (shared with jqlite):

* ``0`` — success.
* ``2`` — CLI/usage error: a missing/extra argument or a bad flag
  (:class:`UsageError`).
* ``4`` — CSV parse error: malformed/undecodable input on stdin
  (:class:`ParseError`).
* ``5`` — query error: an unknown column name or an out-of-range 1-based index
  (and — once the later query surface lands — a malformed predicate)
  (:class:`QueryError`).

Every error message is written to stderr; the exit code is read off the raised
error's ``exit_code``.
"""

from __future__ import annotations

#: Exit status for a CLI/usage error (a missing or extra positional argument, or
#: an unknown flag).
EXIT_USAGE = 2

#: Exit status for a CSV parse error (malformed input on stdin).
EXIT_PARSE = 4

#: Exit status for a query error (an unknown column name or an out-of-range
#: 1-based index; later, a malformed predicate).
EXIT_QUERY = 5


class CsvliteError(Exception):
    """Base class for csvlite errors.

    ``exit_code`` is the process exit status the error maps to.
    """

    exit_code: int = 1


class UsageError(CsvliteError):
    """A CLI/usage error.

    Raised when invocation arguments are wrong: a missing column argument, an
    unexpected extra positional argument, or an unknown flag. Maps to exit
    code 2.
    """

    exit_code = EXIT_USAGE


class ParseError(CsvliteError):
    """A CSV parse error.

    Raised when the input read from stdin is not well-formed CSV. Maps to exit
    code 4.
    """

    exit_code = EXIT_PARSE


class QueryError(CsvliteError):
    """A query error.

    Raised when the column selection references something that does not exist —
    an unknown column name or an out-of-range 1-based index. Maps to exit
    code 5.
    """

    exit_code = EXIT_QUERY
