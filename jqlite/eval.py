"""Evaluate a parsed jqlite query (a list of steps) against a JSON value.

Most steps map one input value to one output value, but iteration ``[]`` and the
filter ``select(f)`` map one input to *many* (or zero) outputs, so evaluation is
a stream-to-stream transformation: :func:`evaluate_stream` threads a list of
values through the steps, branching at each step. :func:`evaluate` is a
single-result convenience for queries without iteration.

Each step type is handled by a small named function registered in
:data:`_STEP_HANDLERS`, a mapping from AST node type to handler. Every handler
takes the current value and its step and returns the *list* of values that the
value expands into (one element for the single-valued steps, zero-or-more for
``[]`` / ``select`` / ``map``); :func:`evaluate_stream` simply concatenates those
lists across the stream.

Field access requires an object, index access requires an array, iteration
requires an array or object, and ``map(f)`` requires an array; applying any to a
value of the wrong type raises :class:`QueryError` (exit code 5) with a message
naming the operation and the offending type and value. ``select(f)`` runs the
inner filter on the input and emits the input once per truthy result of ``f``
(in jq every value except ``false`` and ``null`` is truthy); ``map(f)`` applies
``f`` to each element of an array and collects all results into a new array.

The builtins each map one value to one value: ``keys`` returns the sorted object
keys or the array indices, ``length`` the size/length by JSON type, ``type`` the
JSON type name, and ``has(k)`` a boolean membership test for the literal key.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from jqlite.errors import QueryError
from jqlite.parser import Field, Has, Index, Iterate, Keys, Length, Map, Select, Step, Type

_RENDER_MAX = 60

#: A step handler maps ``(value, step)`` to the list of result values the step
#: produces for that single input. Single-valued steps return a one-element
#: list; iteration / ``select`` / ``map`` may return zero or more.
StepHandler = Callable[[Any, Any], list[Any]]


def evaluate_stream(value: Any, steps: list[Step]) -> list[Any]:
    """Apply ``steps`` to ``value`` and return the stream of results.

    Each step transforms the current stream: field and index access map every
    value to one value; iteration ``[]`` replaces each value with the elements of
    an array (or the values of an object); ``select(f)`` keeps each value only
    when ``f`` is truthy for it; ``map(f)`` maps each value (an array) to the
    array of results of ``f`` over its elements; the builtins ``keys`` /
    ``length`` / ``type`` / ``has(k)`` each map every value to one value. An empty
    ``steps`` list is the identity query and yields ``[value]``.

    Each step is dispatched through :data:`_STEP_HANDLERS` to its handler, whose
    per-value result lists are concatenated to form the next stream.
    """
    results: list[Any] = [value]
    for step in steps:
        handler = _STEP_HANDLERS[type(step)]
        nxt: list[Any] = []
        for current in results:
            nxt.extend(handler(current, step))
        results = nxt
    return results


def evaluate(value: Any, steps: list[Step]) -> Any:
    """Apply ``steps`` to ``value`` and return the single addressed value.

    A single-result convenience over :func:`evaluate_stream` for queries without
    iteration (every step then yields exactly one value). An empty ``steps`` list
    is the identity query and returns ``value`` unchanged. Returns ``None`` when
    the stream is empty (e.g. a ``select(f)`` that dropped the value).
    """
    results = evaluate_stream(value, steps)
    return results[0] if results else None


def _wrong_type(operation: str, expectation: str, value: Any) -> QueryError:
    """Build the uniform wrong-type ``QueryError`` for a step applied to ``value``.

    Every value-type mismatch (field access on a non-object, indexing a
    non-array, iterating a scalar, ``map``/``keys``/``length`` on the wrong type)
    shares the same shape: it names the ``operation``, what it ``expectation``\\ s,
    and the offending value's JSON type and rendering.
    """
    return QueryError(
        f"{operation} requires {expectation}, "
        f"but the value is a {json_type(value)} ({render(value)})"
    )


def _step_field(value: Any, step: Field) -> list[Any]:
    if not isinstance(value, dict):
        raise _wrong_type(f"field access '.{step.name}'", "an object", value)
    # A missing key addresses null, matching jq.
    return [value.get(step.name)]


def _step_index(value: Any, step: Index) -> list[Any]:
    # bool is a subclass of int but is not an array; only list is indexable.
    if not isinstance(value, list):
        raise _wrong_type(f"index access '[{step.n}]'", "an array", value)
    try:
        return [value[step.n]]
    except IndexError:
        # An out-of-range index addresses null, matching jq.
        return [None]


def _step_iterate(value: Any, step: Iterate) -> list[Any]:
    # Arrays iterate their elements; objects iterate their values, both in input
    # order (json.loads and dict preserve insertion order). bool/number/string/
    # null are not iterable.
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return list(value.values())
    raise _wrong_type("iteration '[]'", "an array or object", value)


def _step_select(value: Any, step: Select) -> list[Any]:
    # Run the inner filter on the input; emit the input once for each truthy
    # result (jq's `def select(f): if f then . else empty end;`). The usual case
    # is a single inner result, giving keep-when-truthy / drop-otherwise.
    inner_results = evaluate_stream(value, list(step.inner))
    return [value for result in inner_results if _truthy(result)]


def _step_map(value: Any, step: Map) -> list[Any]:
    # jq's `def map(f): [.[] | f];`, restricted to arrays here: apply the inner
    # filter to each element and concatenate all of its results into a new array.
    if not isinstance(value, list):
        raise _wrong_type("map(...)", "an array", value)
    inner = list(step.inner)
    elements: list[Any] = []
    for element in value:
        elements.extend(evaluate_stream(element, inner))
    return [elements]


def _step_keys(value: Any, step: Keys) -> list[Any]:
    # jq's `keys`: an object yields its keys sorted; an array yields its indices
    # 0..len-1. Scalars have no keys.
    if isinstance(value, dict):
        return [sorted(value.keys())]
    if isinstance(value, list):
        return [list(range(len(value)))]
    raise _wrong_type("keys", "an object or array", value)


def _step_length(value: Any, step: Length) -> list[Any]:
    return [_length_of(value)]


def _step_type(value: Any, step: Type) -> list[Any]:
    return [json_type(value)]


def _step_has(value: Any, step: Has) -> list[Any]:
    return [_has_key(value, step.key)]


#: AST node type -> the handler that evaluates one value through that step.
_STEP_HANDLERS: dict[type, StepHandler] = {
    Field: _step_field,
    Index: _step_index,
    Iterate: _step_iterate,
    Select: _step_select,
    Map: _step_map,
    Keys: _step_keys,
    Length: _step_length,
    Type: _step_type,
    Has: _step_has,
}


def _length_of(value: Any) -> Any:
    # jq's `length`: null -> 0, number -> absolute value, string -> codepoint
    # count, array/object -> element/key count. A boolean has no length.
    length_expectation = "null, a number, string, array, or object"
    if value is None:
        return 0
    if isinstance(value, bool):
        raise _wrong_type("length", length_expectation, value)
    if isinstance(value, (int, float)):
        return abs(value)
    if isinstance(value, (str, list, dict)):
        return len(value)
    raise _wrong_type("length", length_expectation, value)


def _has_key(value: Any, key: str | int) -> bool:
    # jq's `has(k)`: an object tests key membership (k must be a string); an array
    # tests whether index k is in range 0..len-1 (k must be an integer).
    if isinstance(value, dict):
        if not isinstance(key, str):
            raise QueryError(
                f"has({render(key)}) on an object requires a string key, "
                f"but the key is a {json_type(key)}"
            )
        return key in value
    if isinstance(value, list):
        # bool is a subclass of int but is not a valid index.
        if isinstance(key, bool) or not isinstance(key, int):
            raise QueryError(
                f"has({render(key)}) on an array requires an integer index, "
                f"but the key is a {json_type(key)}"
            )
        return 0 <= key < len(value)
    raise _wrong_type("has(...)", "an object or array", value)


def _truthy(value: Any) -> bool:
    """jq truthiness: every value is truthy except ``false`` and ``null``."""
    return value is not None and value is not False


def json_type(value: Any) -> str:
    """Return the JSON type name of ``value``."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def render(value: Any) -> str:
    """Render ``value`` as compact JSON for an error message, truncated if long."""
    text = json.dumps(value, ensure_ascii=False)
    if len(text) > _RENDER_MAX:
        text = text[:_RENDER_MAX] + "..."
    return text
