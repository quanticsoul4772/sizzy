"""Command-line interface for csvlite.

Reads CSV from stdin via the stdlib :mod:`csv` module, treating the first row as
the header (the column names). A single required positional argument is a
comma-separated list of column selectors choosing the columns to emit, in the
order given. Each selector is either a header *name* (e.g. ``name,age``) or a
*1-based index* into the header (e.g. ``1,3`` — the first and third columns).
The two forms may be mixed (e.g. ``name,3``). Selection both projects to and
reorders by the listed columns, regardless of their position in the input. The
header plus each data row, projected to the selected columns, is written back to
stdout as CSV.

CSV input is parsed RFC-4180-style by the stdlib :mod:`csv` module: a quoted
field may contain the delimiter (an embedded comma), an embedded newline, or an
escaped quote (a doubled ``""``), and the field's contents are preserved
verbatim. Any output field that would itself contain the delimiter, a quote, or
a newline is re-quoted by :class:`csv.writer` so the emitted CSV round-trips. To
make this correct on the real process streams, :func:`main` reads stdin and
writes stdout with ``newline=""`` (the documented contract of the :mod:`csv`
module): the csv reader/writer then controls line splitting itself, so the text
layer's universal-newline translation cannot corrupt a newline embedded inside a
quoted field.

A selector made entirely of ASCII digits is read as a 1-based index; anything
else is read as a header name. (A column literally named ``1`` is therefore only
reachable as an index — an accepted v1 trade-off.)

An optional ``--where 'COLUMN OP VALUE'`` flag filters the data rows before
selection: only rows for which the comparison holds are emitted. ``OP`` is one
of the six comparison operators ``== != < <= > >=``. Each comparison is numeric
when *both* the cell and ``VALUE`` parse as numbers, and a plain string
comparison otherwise (so ``--where 'age >= 36'`` orders the cell ``"36.0"``
numerically, while ``--where 'city < NYC'`` orders as text). The predicate's
``COLUMN`` is resolved against the input header by name; an unknown column or a
malformed predicate is a query error.

By default the output is CSV (header + selected/filtered rows, csv-module
quoted). The optional ``--json`` flag instead emits a JSON array of objects, one
per surviving data row, each keyed by the selected header names (in the selected
order) with the row's cell values as strings. Header-only or fully-filtered
input emits an empty array (``[]``). ``--json`` composes with column selection
and ``--where`` exactly as the CSV path does.

Exit codes (all error messages go to stderr, specific and clear):

* ``0`` — success.
* ``2`` — CLI/usage error: a missing column argument, an empty column selector
  (e.g. ``""`` or a trailing comma), an unknown flag, a flag missing its
  argument, or an unexpected extra argument.
* ``4`` — CSV parse error: the input on stdin is malformed CSV (e.g. a field
  larger than the csv module's field-size limit) or undecodable (the byte
  stream is not valid text under the active encoding).
* ``5`` — query error: an unknown column name, an out-of-range 1-based index, or
  a malformed ``--where`` predicate.
"""

from __future__ import annotations

import csv
import json
import sys
from typing import IO

from csvlite.errors import CsvliteError, ParseError, QueryError, UsageError

#: The two-character comparison operators, checked before the one-character
#: forms so the parser prefers e.g. ``<=`` over ``<`` and ``>=`` over ``>``.
_TWO_CHAR_OPS = ("==", "!=", "<=", ">=")

#: The one-character comparison operators.
_ONE_CHAR_OPS = ("<", ">")

#: All six comparison operators supported in a ``--where`` predicate.
OPERATORS = _TWO_CHAR_OPS + _ONE_CHAR_OPS


def _parse_args(argv: list[str]) -> tuple[str, str | None, bool]:
    """Parse ``argv`` into ``(column_spec, where_predicate, want_json)``.

    ``column_spec`` is the single positional column-spec string. ``where`` is
    the raw ``--where`` predicate string, or ``None`` when the flag is absent.
    ``want_json`` is ``True`` when the ``--json`` flag was given. Supports both
    ``--where PRED`` and ``--where=PRED`` forms.

    The following invocation errors all raise :class:`UsageError` (exit code 2),
    because they are problems with *how the command was invoked* rather than with
    the data on stdin or the columns it references:

    * a missing column argument (no positional given);
    * an empty column argument (``""`` or whitespace-only) or one that contains
      an empty selector (e.g. a leading/trailing/doubled comma like ``name,``);
    * an unknown flag;
    * a ``--where`` flag missing its argument;
    * more than one positional argument.
    """
    positionals: list[str] = []
    where: str | None = None
    want_json = False

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--where":
            i += 1
            if i >= len(argv):
                raise UsageError(
                    "--where requires an argument 'COLUMN OP VALUE'"
                )
            where = argv[i]
        elif arg.startswith("--where="):
            where = arg[len("--where=") :]
        elif arg == "--json":
            want_json = True
        elif arg.startswith("-") and arg != "-":
            raise UsageError(f"unknown option {arg!r}")
        else:
            positionals.append(arg)
        i += 1

    if not positionals:
        raise UsageError(
            "no columns given; a comma-separated column argument is required"
        )
    if len(positionals) > 1:
        extras = ", ".join(repr(p) for p in positionals[1:])
        raise UsageError(f"unexpected extra argument(s): {extras}")

    spec = positionals[0]
    if not spec.strip():
        raise UsageError(
            "no columns given; a comma-separated column argument is required"
        )
    if any(not selector.strip() for selector in spec.split(",")):
        raise UsageError(
            f"invalid column argument {spec!r}: an empty column selector is "
            f"not allowed"
        )

    return spec, where, want_json


def _as_index(token: str) -> int | None:
    """Return the 1-based index a selector ``token`` denotes, or ``None``.

    A selector made entirely of ASCII digits (e.g. ``"3"``) is a 1-based index;
    anything else (a header name, a signed/padded form, a non-ASCII digit) is
    not, and is resolved by name instead.
    """
    if token.isascii() and token.isdigit():
        return int(token)
    return None


def select_columns(header: list[str], spec: str) -> tuple[list[int], list[str]]:
    """Resolve a comma-separated column ``spec`` against ``header``.

    Each selector is either a header *name* or a *1-based index* (an all-digits
    token). Returns ``(indices, names)`` where ``indices`` are the resolved
    0-based positions in ``header`` and ``names`` are the corresponding header
    names, both in the requested order. On a duplicate header name the first
    occurrence wins. An unknown name or an out-of-range index raises
    :class:`QueryError` (exit code 5).
    """
    index_of: dict[str, int] = {}
    for i, name in enumerate(header):
        index_of.setdefault(name, i)

    indices: list[int] = []
    out_names: list[str] = []
    for token in spec.split(","):
        pos = _as_index(token)
        if pos is not None:
            if pos < 1 or pos > len(header):
                raise QueryError(
                    f"column index {pos} out of range (1..{len(header)})"
                )
            idx = pos - 1
            indices.append(idx)
            out_names.append(header[idx])
        else:
            if token not in index_of:
                raise QueryError(f"unknown column {token!r}")
            indices.append(index_of[token])
            out_names.append(token)
    return indices, out_names


def _find_operator(text: str) -> tuple[int, str] | None:
    """Return ``(index, op)`` of the first comparison operator in ``text``.

    Scans left to right; at each position the two-character operators are tried
    before the one-character ones, so ``<=`` / ``>=`` are never mis-read as a
    lone ``<`` / ``>``. Returns ``None`` when no operator is present. A bare
    ``=`` is not an operator (only ``==`` is), so it is not matched.
    """
    for i in range(len(text)):
        for op in _TWO_CHAR_OPS:
            if text.startswith(op, i):
                return i, op
        for op in _ONE_CHAR_OPS:
            if text.startswith(op, i):
                return i, op
    return None


def parse_predicate(text: str) -> tuple[str, str, str]:
    """Parse a ``--where`` predicate ``'COLUMN OP VALUE'``.

    Returns ``(column, op, value)`` where ``op`` is one of the six comparison
    operators ``== != < <= > >=``. The split is made at the first operator
    occurrence (two-character forms take precedence over one-character ones).
    ``column`` is stripped of surrounding whitespace; ``value`` is the remainder
    after the operator, also stripped (an empty ``value`` is allowed and matches
    empty cells under equality). A predicate with no recognised operator or an
    empty column name is malformed and raises :class:`QueryError` (exit code 5).
    """
    found = _find_operator(text)
    if found is None:
        raise QueryError(
            f"malformed predicate {text!r}: expected 'COLUMN OP VALUE' with "
            f"OP one of == != < <= > >="
        )
    i, op = found
    column = text[:i].strip()
    value = text[i + len(op) :].strip()
    if not column:
        raise QueryError(
            f"malformed predicate {text!r}: empty column name"
        )
    return column, op, value


def _as_number(text: str) -> float | None:
    """Return ``text`` parsed as a float, or ``None`` if it is not a number."""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def compare_cell(cell: str, op: str, value: str) -> bool:
    """Return whether ``cell OP value`` holds for the ``--where`` predicate.

    The comparison is numeric when *both* ``cell`` and ``value`` parse as
    numbers (so ``"36"`` orders against ``"36.0"`` numerically); otherwise both
    sides are compared as plain strings. ``op`` is one of the six comparison
    operators ``== != < <= > >=``.
    """
    cell_num = _as_number(cell)
    value_num = _as_number(value)
    if cell_num is not None and value_num is not None:
        left: float | str = cell_num
        right: float | str = value_num
    else:
        left = cell
        right = value

    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right  # type: ignore[operator]
    if op == "<=":
        return left <= right  # type: ignore[operator]
    if op == ">":
        return left > right  # type: ignore[operator]
    if op == ">=":
        return left >= right  # type: ignore[operator]
    raise QueryError(f"unsupported operator {op!r}")


def cell_matches(cell: str, value: str) -> bool:
    """Return whether ``cell`` equals ``value`` (the ``==`` predicate).

    A thin wrapper over :func:`compare_cell` for the equality operator, kept for
    callers and tests that only need equality.
    """
    return compare_cell(cell, "==", value)


def _resolve_where_column(header: list[str], column: str) -> int:
    """Return the 0-based index of ``column`` in ``header`` (first match wins).

    An unknown column raises :class:`QueryError` (exit code 5).
    """
    for i, name in enumerate(header):
        if name == column:
            return i
    raise QueryError(f"unknown column {column!r} in --where predicate")


def _project_row(row: list[str], indices: list[int]) -> list[str]:
    """Return ``row`` projected to ``indices``, padding short rows with ``""``."""
    return [row[i] if i < len(row) else "" for i in indices]


def _read_rows(stdin: IO[str]) -> list[list[str]]:
    """Read all CSV rows from ``stdin`` via the stdlib :mod:`csv` reader.

    Two distinct stdin failures are normalised to a :class:`ParseError` (exit
    code 4): a :class:`csv.Error` (the bytes decode to text but are not
    well-formed CSV — e.g. a field larger than ``csv.field_size_limit()``), and
    a :class:`UnicodeDecodeError` (the byte stream is not valid text under the
    active encoding, so it cannot be decoded at all). Both are content problems
    with the input on stdin, not invocation or query problems, so both map to
    the parse-error code rather than surfacing as an uncaught traceback.
    """
    try:
        return list(csv.reader(stdin))
    except csv.Error as exc:
        raise ParseError(f"malformed CSV on stdin: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ParseError(f"undecodable input on stdin: {exc}") from exc


def _reconfigure_newline(stream: object) -> None:
    """Set ``newline=""`` on a real text stream so the csv module owns line
    splitting.

    The stdlib :mod:`csv` module's documented contract is that its source/sink
    be opened with ``newline=""``; otherwise the text layer's universal-newline
    translation corrupts a newline embedded inside a quoted field (it produces
    spurious empty rows on read and injects a stray ``\\r`` on write). Real
    process streams expose ``reconfigure``; injected test streams (e.g.
    :class:`io.StringIO`) do not and are left untouched, since they already
    preserve embedded newlines verbatim.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(newline="")


def main(
    argv: list[str] | None = None,
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    """Run csvlite.

    Reads CSV from ``stdin`` (first row = header), optionally filters the data
    rows with a single ``--where 'COLUMN OP VALUE'`` predicate (``OP`` one of
    ``== != < <= > >=``), selects/reorders the columns named or indexed by the
    single positional argument, and writes the projected header and surviving
    rows back to ``stdout``. Quoted fields with embedded commas, embedded
    newlines, or escaped quotes are parsed by the stdlib :mod:`csv` module and
    re-quoted on output so the CSV round-trips. Output is CSV by default; with
    ``--json`` it is a JSON array of objects, one per surviving row, keyed by the
    selected header names. Returns 0 on success; on error writes a clear message
    to ``stderr`` and returns a distinct exit code (2 usage — a missing/empty/
    extra argument or a bad flag, 4 CSV parse — both malformed and undecodable
    input, 5 query). The stream/IO objects are injectable for testing; they
    default to the real process streams (which are reconfigured to ``newline=""``
    so the csv reader/writer handles embedded newlines correctly).
    """
    if argv is None:
        argv = sys.argv[1:]
    if stdin is None:
        stdin = sys.stdin
        _reconfigure_newline(stdin)
    if stdout is None:
        stdout = sys.stdout
        _reconfigure_newline(stdout)
    if stderr is None:
        stderr = sys.stderr

    try:
        spec, where, want_json = _parse_args(argv)
        rows = _read_rows(stdin)

        header = rows[0] if rows else []
        indices, out_names = select_columns(header, spec)

        data_rows = rows[1:]
        if where is not None:
            column, op, value = parse_predicate(where)
            where_idx = _resolve_where_column(header, column)
            data_rows = [
                row
                for row in data_rows
                if compare_cell(
                    row[where_idx] if where_idx < len(row) else "", op, value
                )
            ]

        if want_json:
            records = [
                dict(zip(out_names, _project_row(row, indices)))
                for row in data_rows
            ]
            json.dump(records, stdout, ensure_ascii=False)
            stdout.write("\n")
        else:
            writer = csv.writer(stdout, lineterminator="\n")
            writer.writerow(out_names)
            for row in data_rows:
                writer.writerow(_project_row(row, indices))
    except CsvliteError as exc:
        stderr.write(f"csvlite: {exc}\n")
        return exc.exit_code
    return 0
