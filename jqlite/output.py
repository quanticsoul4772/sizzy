"""Serialization of query results to JSON for stdout.

Two *plain* output forms, each byte-for-byte deterministic for a given value:

* the default *pretty* form — 2-space-indented, multi-line JSON;
* the *compact* form (``-c`` / ``--compact``) — single-line JSON, one result
  per line.

Both echo unicode faithfully (``ensure_ascii=False``) and preserve object key
order (the parse order ``json.loads`` produced — keys are never sorted), so
every result is golden-testable. Each serialized result is newline-terminated,
which is what gives the compact form its "one result per line" guarantee.

An OPTIONAL *color* form (``--color``) pretty-prints with rich's JSON syntax
highlighting. Color is purely additive: it is available only when the optional
``rich`` dependency is installed, and degrades cleanly to the matching plain
form when it is not — jqlite's core stays stdlib-only and runs with no
third-party packages installed.
"""

from __future__ import annotations

import json
from types import ModuleType
from typing import Any

#: Indentation (spaces) for the default pretty form.
_INDENT = 2

#: Item/key separators for the compact form. The defaults json uses when no
#: indent is given are ``(", ", ": ")`` — those embed spaces; the tightest
#: deterministic single-line form drops them.
_COMPACT_SEPARATORS = (",", ":")


def dump_pretty(value: Any) -> str:
    """Serialize ``value`` as 2-space-indented JSON, newline-terminated."""
    return json.dumps(value, indent=_INDENT, ensure_ascii=False) + "\n"


def dump_compact(value: Any) -> str:
    """Serialize ``value`` as single-line compact JSON, newline-terminated."""
    return json.dumps(value, separators=_COMPACT_SEPARATORS, ensure_ascii=False) + "\n"


def _import_rich() -> ModuleType | None:
    """Return the ``rich`` module if it is installed, else ``None``.

    Isolated as a single import seam so the color path's rich-vs-no-rich
    branch has one place to detect availability — and so a test can force the
    no-rich fallback by patching this without uninstalling rich.
    """
    try:
        import rich
    except ImportError:
        return None
    return rich


def dump_color(value: Any, *, compact: bool = False) -> str:
    """Serialize ``value`` as syntax-highlighted JSON using rich.

    Renders the same shape as the plain forms — 2-space pretty by default, or
    single-line when ``compact`` — with rich's JSON highlighting (ANSI escapes),
    newline-terminated. The output is forced to a terminal color profile so the
    highlighting is emitted even when stdout is a captured buffer rather than a
    live TTY.

    Falls back to the matching plain form when rich is not installed, so a
    caller can always request color and still get correct output.
    """
    rich = _import_rich()
    if rich is None:
        return dump(value, compact=compact)

    import io

    from rich.console import Console
    from rich.json import JSON

    indent = None if compact else _INDENT
    rendered = JSON.from_data(value, indent=indent, ensure_ascii=False)

    buffer = io.StringIO()
    console = Console(
        file=buffer,
        force_terminal=True,
        color_system="truecolor",
        soft_wrap=True,
    )
    console.print(rendered)
    return buffer.getvalue()


def dump(value: Any, *, compact: bool = False, color: bool = False) -> str:
    """Serialize ``value`` for stdout.

    Returns the compact single-line form when ``compact`` is true, otherwise the
    default 2-space pretty form. When ``color`` is true and the optional ``rich``
    dependency is installed, the result is syntax-highlighted (still matching the
    pretty/compact shape); without rich, ``color`` is a no-op and the plain form
    is returned. The plain forms are newline-terminated and deterministic for a
    given ``value``.
    """
    if color:
        return dump_color(value, compact=compact)
    return dump_compact(value) if compact else dump_pretty(value)
