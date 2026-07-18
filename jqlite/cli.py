"""Command-line interface for jqlite.

Reads a *stream* of JSON values from stdin — whitespace / NDJSON-separated, like
jq — and applies the query to each value independently, writing each result back
as deterministic JSON. The results of one input value are all emitted before the
next input value is processed, so output preserves input order.

Output is 2-space-indented pretty JSON by default; the ``-c`` / ``--compact``
flag switches to single-line compact JSON, one result per line. Both forms are
byte-for-byte deterministic for a given input. The OPTIONAL ``--color`` flag
syntax-highlights the output using rich when that optional dependency is
installed, and is a clean no-op (plain output) when it is not — jqlite's core
stays stdlib-only.

Query surface (cumulative): identity ``.``, field access ``.a`` / ``.a.b``,
index access ``.[N]``, and iteration ``.[]`` (which emits each array element /
object value as its own result). The query is the required first positional
argument; omitting it is a usage error (exit 2).

Exit codes (all error messages go to stderr, specific and clear):

* ``0`` — success.
* ``2`` — CLI/usage error: a missing query, an unknown flag, or an unexpected
  extra argument.
* ``4`` — JSON parse error: malformed JSON on stdin.
* ``5`` — query or type error: a malformed query, or an operation applied to a
  value of the wrong type (e.g. field access on a non-object).
"""

from __future__ import annotations

import json
import sys
from typing import IO, Any, Iterator

from jqlite.errors import EXIT_PARSE, QueryError, UsageError
from jqlite.eval import evaluate_stream
from jqlite.output import dump
from jqlite.parser import parse_query

# The whitespace characters JSON permits between top-level values; the same set
# json's own decoder skips. A run of any of these (including none, for adjacent
# values like ``{"a":1}{"b":2}``) separates one stream value from the next.
_WS = " \t\n\r"

# The flag spellings that select compact single-line output.
_COMPACT_FLAGS = ("-c", "--compact")

# The flag that selects rich-highlighted output (optional; no-op without rich).
_COLOR_FLAG = "--color"


def identity(value: Any) -> Any:
    """The identity query ``.`` — return the value unchanged."""
    return value


def iter_json_values(text: str) -> Iterator[Any]:
    """Yield each top-level JSON value in ``text``, in order.

    Parses a stream of JSON values separated by JSON whitespace (the NDJSON case
    of one value per line, the space-separated case, and the adjacent case like
    ``{"a":1}{"b":2}`` all fall out of this). Leading/trailing/inter-value
    whitespace is skipped; an empty or whitespace-only string yields nothing.
    Raises :class:`json.JSONDecodeError` on a malformed value; ``main`` catches
    it and maps it to the exit-code-4 parse-error path.
    """
    decoder = json.JSONDecoder()
    idx = 0
    n = len(text)
    while True:
        while idx < n and text[idx] in _WS:
            idx += 1
        if idx >= n:
            return
        value, idx = decoder.raw_decode(text, idx)
        yield value


def _parse_args(argv: list[str]) -> tuple[bool, bool, str]:
    """Parse ``argv`` into ``(compact, color, query)``.

    Recognizes the ``-c`` / ``--compact`` flag, the optional ``--color`` flag
    (either flag in either position relative to the query), and the single
    required positional query. A missing query, an unknown flag, or more than
    one positional argument raises :class:`UsageError` (exit code 2).
    """
    compact = False
    color = False
    positionals: list[str] = []
    for arg in argv:
        if arg in _COMPACT_FLAGS:
            compact = True
        elif arg == _COLOR_FLAG:
            color = True
        elif arg.startswith("-") and arg != "-":
            raise UsageError(f"unknown option {arg!r}")
        else:
            positionals.append(arg)

    if not positionals:
        raise UsageError("no query given; a query argument is required")
    if len(positionals) > 1:
        extras = ", ".join(repr(p) for p in positionals[1:])
        raise UsageError(f"unexpected extra argument(s): {extras}")

    query = positionals[0]
    return compact, color, query


def main(
    argv: list[str] | None = None,
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    """Run jqlite.

    Reads a stream of JSON values from ``stdin`` (whitespace / NDJSON-separated)
    and applies the query (the required first positional argument) to each value
    independently. The ``-c`` / ``--compact`` flag selects single-line compact
    output (one result per line); without it, results are 2-space-indented pretty
    JSON. The optional ``--color`` flag syntax-highlights the output with rich
    when installed (a clean no-op producing plain output otherwise). For every
    input value, all of its result(s) are written to ``stdout`` before the next
    input value is processed, so output preserves input order. Most queries
    produce one result per input; iteration ``.[]`` produces one per
    element/value (zero for an empty collection).

    Returns 0 on success. On error, writes a clear message to ``stderr`` and
    returns a distinct exit code: 2 for a CLI/usage error (a missing query, a bad
    flag, or an extra argument), 4 for a malformed-JSON parse error, or 5 for a
    query/type error. Results already emitted for earlier input values are
    retained when a later value triggers a parse or query error.

    The stream/IO objects are injectable for testing; they default to the real
    process streams.
    """
    if argv is None:
        argv = sys.argv[1:]
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout
    if stderr is None:
        stderr = sys.stderr

    try:
        compact, color, query = _parse_args(argv)
        steps = parse_query(query)
        raw = stdin.read()
        for value in iter_json_values(raw):
            results = evaluate_stream(value, steps)
            for result in results:
                stdout.write(dump(result, compact=compact, color=color))
    except (UsageError, QueryError) as exc:
        stderr.write(f"jqlite: {exc}\n")
        return exc.exit_code
    except json.JSONDecodeError as exc:
        stderr.write(f"jqlite: invalid JSON on stdin: {exc}\n")
        return EXIT_PARSE
    return 0
