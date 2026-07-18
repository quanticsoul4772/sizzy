# jqlite

A dependency-free, standard-library-only jq-style JSON query CLI for Python 3.11+.

## Status

v1 scaffold. Reads a single JSON value from stdin, applies the identity query
`.` (echoing the value unchanged), and pretty-prints the result as
2-space-indented deterministic JSON to stdout, exiting `0`.

## Usage

```sh
echo '{"b": 1, "a": 2}' | python -m jqlite
```

```json
{
  "b": 1,
  "a": 2
}
```

Object key order is preserved from the input (the identity query echoes the
value unchanged), and output is fully deterministic — same input, same bytes.

## Design

- Standard library only; no third-party dependencies.
- Python 3.11+.
- Package layout `jqlite/`, run as `python -m jqlite`.

The full v1 query language (field/index access, iteration, `select`/`map`, and
the `keys`/`length`/`type`/`has` builtins) and the streaming-input / compact-output
/ distinct-exit-code behaviors are built on this scaffold in later tasks.
