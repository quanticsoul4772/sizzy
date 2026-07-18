"""jqlite — a dependency-free, stdlib-only jq-style JSON query CLI.

v1 scaffold: reads a single JSON value from stdin, applies the identity query
``.`` (echoing the value unchanged), and pretty-prints the result as
2-space-indented deterministic JSON to stdout.

Stdlib only; Python 3.11+. Run as ``python -m jqlite``.
"""

from jqlite.cli import identity, main

__all__ = ["main", "identity"]
__version__ = "0.1.0"
