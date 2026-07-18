"""csvlite — a dependency-free, stdlib-only jq-style CSV query CLI.

v1 scaffold: reads CSV from stdin (the first row is the header) via the stdlib
``csv`` module, takes a single positional comma-separated argument naming the
columns to select/reorder by header name or 1-based index (e.g. ``name,age`` or
``1,3``), optionally filters rows with a single ``--where 'COLUMN OP VALUE'``
predicate (``OP`` one of ``== != < <= > >=``), and writes the selected columns —
header plus surviving rows, in the requested order — back out as CSV, or, with
``--json``, as a JSON array of objects keyed by the selected header names.

Stdlib only; Python 3.11+. Run as ``python -m csvlite``.
"""

from csvlite.cli import cell_matches, main, parse_predicate, select_columns

__all__ = ["main", "select_columns", "parse_predicate", "cell_matches"]
__version__ = "0.1.0"
