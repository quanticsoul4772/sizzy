"""Parse a jqlite query string into a sequence of access steps.

Supported surface (cumulative): identity ``.``, field access ``.a`` and chained
``.a.b``, index access ``.[N]`` (also written ``.a[N]`` / ``.a.[N]``), iteration
``.[]`` (also ``.a[]`` / ``.a.[]``), which emits each element of an array or each
value of an object, the filter calls ``select(f)`` and ``map(f)`` (whose argument
``f`` is itself a jqlite query parsed recursively), and the builtins ``keys``,
``length``, ``type`` (each taking no argument) and ``has(k)`` (taking a literal
JSON string or integer key). A query that falls outside this surface raises
:class:`QueryError`.

Anything outside the v1 surface — pipes (``|``), arithmetic (``+ - * / %``),
comparison/boolean operators (``== != < > <= >=`` and the word operators
``and`` / ``or`` / ``not``), assignment/update (``= |=`` …), string
interpolation (``\\(...)``), recursive descent (``..``), and any unknown filter
or builtin name — is rejected as a :class:`QueryError` whose message names the
specific unsupported construct.
"""

from __future__ import annotations

import json
import string
from dataclasses import dataclass

from jqlite.errors import QueryError

_IDENT_START = frozenset(string.ascii_letters + "_")
_IDENT_CONT = frozenset(string.ascii_letters + string.digits + "_")

#: Whitespace characters tolerated between an operand and a following operator
#: (so ``.a | .b`` and ``.a == 1`` report the operator, not the gap).
_WHITESPACE = frozenset(" \t\n\r\f\v")

#: Filter functions that take a parenthesized inner query: ``select(f)``,
#: ``map(f)``.
_FILTERS = frozenset({"select", "map"})

#: Builtins that take no argument: ``keys``, ``length``, ``type``.
_NULLARY_BUILTINS = frozenset({"keys", "length", "type"})

#: Word-form operators that are out of scope for v1, mapped to the
#: human-readable description used in the rejection message.
_WORD_OPERATORS = {
    "and": "the boolean operator 'and'",
    "or": "the boolean operator 'or'",
    "not": "the boolean operator 'not'",
}

#: Two-character symbolic operators that are out of scope for v1. Checked
#: before the single-character table so ``==`` is not misread as ``=``.
_TWO_CHAR_OPERATORS = {
    "==": "the comparison operator '=='",
    "!=": "the comparison operator '!='",
    "<=": "the comparison operator '<='",
    ">=": "the comparison operator '>='",
    "|=": "the update-assignment operator '|='",
    "+=": "the update-assignment operator '+='",
    "-=": "the update-assignment operator '-='",
    "*=": "the update-assignment operator '*='",
    "/=": "the update-assignment operator '/='",
    "//": "the alternative operator '//'",
}

#: Single-character symbolic operators that are out of scope for v1.
_ONE_CHAR_OPERATORS = {
    "|": "the pipe operator '|'",
    "+": "the arithmetic operator '+'",
    "-": "the arithmetic operator '-'",
    "*": "the arithmetic operator '*'",
    "/": "the arithmetic operator '/'",
    "%": "the arithmetic operator '%'",
    "<": "the comparison operator '<'",
    ">": "the comparison operator '>'",
    "=": "the assignment operator '='",
    "!": "the boolean operator '!'",
    "\\": "string interpolation",
}


@dataclass(frozen=True)
class Field:
    """Field access ``.name`` — select ``name`` from an object."""

    name: str


@dataclass(frozen=True)
class Index:
    """Index access ``[n]`` — select position ``n`` from an array."""

    n: int


@dataclass(frozen=True)
class Iterate:
    """Iteration ``[]`` — emit each element of an array / value of an object."""


@dataclass(frozen=True)
class Select:
    """``select(f)`` — emit the input only when the inner filter ``f`` is truthy.

    ``inner`` is the parsed inner query (a tuple of steps so the dataclass stays
    hashable/frozen); the empty tuple is the identity filter ``select(.)``.
    """

    inner: tuple["Step", ...]


@dataclass(frozen=True)
class Map:
    """``map(f)`` — apply ``f`` to each element of an array, returning an array.

    ``inner`` is the parsed inner query (a tuple of steps); the empty tuple is
    the identity filter ``map(.)``.
    """

    inner: tuple["Step", ...]


@dataclass(frozen=True)
class Keys:
    """``keys`` — sorted object keys, or array indices ``0..len-1``."""


@dataclass(frozen=True)
class Length:
    """``length`` — size/length of the value, by JSON type."""


@dataclass(frozen=True)
class Type:
    """``type`` — the JSON type name of the value as a string."""


@dataclass(frozen=True)
class Has:
    """``has(k)`` — test whether the input has key/index ``k``.

    ``key`` is a literal string (object membership) or integer (array index),
    captured at parse time from the call's ``(...)`` argument.
    """

    key: str | int


Step = Field | Index | Iterate | Select | Map | Keys | Length | Type | Has


def parse_query(query: str) -> list[Step]:
    """Parse ``query`` into a list of access steps.

    The empty list represents the identity query ``.``. A query is built from
    dot-path steps (``.``, ``.a.b``, ``.[0]``, ``.[]`` …), filter calls
    (``select(f)`` / ``map(f)``) and builtins (``keys`` / ``length`` / ``type`` /
    ``has(k)``); steps may juxtapose (``map(.x)[0]``, ``.[]keys``). Raises
    :class:`QueryError` on any input outside the supported surface — including
    any out-of-scope operator, filter, or builtin, whose message names the
    unsupported construct.
    """
    s = query.strip()
    if not s:
        raise QueryError(f"invalid query {query!r}: a query must not be empty")
    if not (s.startswith(".") or s[0] in _IDENT_START):
        construct = _classify_operator(s, 0)
        if construct is not None:
            raise _unsupported(construct, query)
        raise QueryError(
            f"invalid query {query!r}: a query must begin with '.' or a filter"
        )

    steps: list[Step] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == ".":
            i += 1
            if i >= n:
                if not steps:
                    break  # bare '.' is identity
                raise QueryError(f"invalid query {query!r}: trailing '.'")
            if s[i] == ".":
                raise _unsupported("recursive descent '..'", query)
            if s[i] == "[":
                continue  # the '.[...]' form; handled by the '[' branch below
            name, i = _read_ident(s, i, query)
            steps.append(Field(name))
        elif c == "[":
            step, i = _read_bracket(s, i, query)
            steps.append(step)
        elif c in _IDENT_START:
            step, i = _read_filter(s, i, query)
            steps.append(step)
        else:
            raise _unsupported_or_unexpected(s, i, query)
    return steps


def _classify_operator(s: str, i: int) -> str | None:
    """If an out-of-scope symbolic operator begins at ``s[i]``, return its
    human-readable description; otherwise ``None``.

    Two-character operators (``==``, ``|=`` …) are matched before single
    characters so they are described precisely rather than as their prefix.
    """
    two = s[i : i + 2]
    if two in _TWO_CHAR_OPERATORS:
        return _TWO_CHAR_OPERATORS[two]
    one = s[i]
    if one in _ONE_CHAR_OPERATORS:
        return _ONE_CHAR_OPERATORS[one]
    return None


def _unsupported(description: str, query: str) -> QueryError:
    """Build the uniform ``QueryError`` naming an out-of-scope construct."""
    return QueryError(
        f"unsupported query {query!r}: {description} is not supported in "
        f"jqlite v1"
    )


def _unsupported_or_unexpected(s: str, i: int, query: str) -> QueryError:
    """Classify the character at ``s[i]`` that cannot begin a step.

    Whitespace before the offending token is skipped so ``.a | .b`` and
    ``.a and .b`` name the operator rather than the gap. If an out-of-scope
    symbolic or word operator is found, the error names that construct;
    otherwise it reports the unexpected character at its original position.
    """
    n = len(s)
    j = i
    while j < n and s[j] in _WHITESPACE:
        j += 1
    if j < n:
        construct = _classify_operator(s, j)
        if construct is not None:
            return _unsupported(construct, query)
        if s[j] in _IDENT_START:
            word = _peek_ident(s, j)
            if word in _WORD_OPERATORS:
                return _unsupported(_WORD_OPERATORS[word], query)
    return QueryError(
        f"invalid query {query!r}: unexpected character {s[i]!r} at position {i}"
    )


def _peek_ident(s: str, i: int) -> str:
    """Read the identifier starting at ``s[i]`` without raising (lookahead)."""
    n = len(s)
    start = i
    i += 1
    while i < n and s[i] in _IDENT_CONT:
        i += 1
    return s[start:i]


def _read_ident(s: str, i: int, query: str) -> tuple[str, int]:
    n = len(s)
    if i >= n or s[i] not in _IDENT_START:
        raise QueryError(
            f"invalid query {query!r}: expected a field name at position {i}"
        )
    start = i
    i += 1
    while i < n and s[i] in _IDENT_CONT:
        i += 1
    return s[start:i], i


def _read_bracket(s: str, i: int, query: str) -> tuple[Step, int]:
    # s[i] == '['
    close = s.find("]", i)
    if close == -1:
        raise QueryError(f"invalid query {query!r}: unclosed '['")
    inner = s[i + 1 : close].strip()
    if inner == "":
        # Empty brackets '[]' are iteration.
        return Iterate(), close + 1
    try:
        num = int(inner)
    except ValueError:
        raise QueryError(
            f"invalid query {query!r}: index must be an integer, got {inner!r}"
        )
    return Index(num), close + 1


def _read_filter(s: str, i: int, query: str) -> tuple[Step, int]:
    """Parse a named step starting at the identifier ``s[i]``.

    Dispatches on the name: ``select`` / ``map`` take a recursively parsed query
    argument; ``keys`` / ``length`` / ``type`` take no argument; ``has`` takes a
    literal JSON string or integer key. A word operator (``and`` / ``or`` /
    ``not``) or any other unknown name is rejected as an out-of-scope construct.
    """
    name, j = _read_ident(s, i, query)
    n = len(s)

    if name in _NULLARY_BUILTINS:
        if j < n and s[j] == "(":
            raise QueryError(
                f"invalid query {query!r}: builtin {name!r} takes no argument"
            )
        step = {"keys": Keys(), "length": Length(), "type": Type()}[name]
        return step, j

    if name == "has":
        if j >= n or s[j] != "(":
            raise QueryError(
                f"invalid query {query!r}: has(k) requires a key argument, "
                f"e.g. has(\"name\") or has(0)"
            )
        inner_src, after = _read_parens(s, j, query)
        return Has(_parse_has_arg(inner_src, query)), after

    if name in _FILTERS:
        if j >= n or s[j] != "(":
            raise QueryError(
                f"invalid query {query!r}: filter {name!r} requires a parenthesized "
                f"argument, e.g. {name}(.field)"
            )
        inner_src, after = _read_parens(s, j, query)
        inner_steps = tuple(parse_query(inner_src))
        if name == "select":
            return Select(inner_steps), after
        return Map(inner_steps), after

    if name in _WORD_OPERATORS:
        raise _unsupported(_WORD_OPERATORS[name], query)

    raise QueryError(
        f"unsupported query {query!r}: {name!r} is not a supported filter or "
        f"builtin in jqlite v1"
    )


def _parse_has_arg(src: str, query: str) -> str | int:
    """Parse the literal key argument of ``has(k)``.

    The argument is a JSON string (``has("name")``) or integer (``has(0)``).
    Anything else — empty, a float, a boolean, ``null``, an array/object, or
    non-JSON text — is a query error.
    """
    text = src.strip()
    if text == "":
        raise QueryError(
            f"invalid query {query!r}: has(k) requires a key argument"
        )
    try:
        key = json.loads(text)
    except ValueError:
        raise QueryError(
            f"invalid query {query!r}: has(...) argument must be a string or "
            f"integer literal, got {text!r}"
        )
    # bool is a subclass of int; exclude it (and floats / null / containers).
    if isinstance(key, bool) or not isinstance(key, (str, int)):
        raise QueryError(
            f"invalid query {query!r}: has(...) argument must be a string or "
            f"integer literal, got {text!r}"
        )
    return key


def _read_parens(s: str, i: int, query: str) -> tuple[str, int]:
    """Return the text inside the balanced parentheses opening at ``s[i]``.

    Tracks nesting depth so a filter argument may itself contain parentheses
    (``map(select(.a))``). Returns the inner text and the index just past the
    matching ``)``.
    """
    # s[i] == '('
    depth = 0
    start = i + 1
    n = len(s)
    j = i
    while j < n:
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return s[start:j], j + 1
        j += 1
    raise QueryError(f"invalid query {query!r}: unclosed '(' in filter call")
