# csvlite

A dependency-free, stdlib-only jq-style command-line tool for CSV — the CSV
analogue of jqlite. Python 3.11+, stdlib only (the `csv` module). Run as
`python -m csvlite`.

## Scaffold scope (v1.x)

Reads CSV from **stdin** (the first row is the header) and takes a single
positional **comma-separated list of column selectors** choosing the columns to
emit, in the order given. Each selector is either a column **name** or a
**1-based index** into the header (the two forms may be mixed). The selected
header and rows are written to **stdout** as CSV.

```sh
printf 'name,age,city\nAda,36,London\nGrace,40,NYC\n' | python -m csvlite name,age
# name,age
# Ada,36
# Grace,40

# select/reorder by 1-based index — '1,3' picks columns 1 and 3:
printf 'name,age,city\nAda,36,London\n' | python -m csvlite 1,3
# name,city
# Ada,London

# reorder by listing the columns in a different order (name or index):
printf 'name,age,city\nAda,36,London\n' | python -m csvlite city,name
# city,name
# London,Ada
```

A selector made entirely of digits is read as a 1-based index; anything else is
read as a header name. (A column literally named `1` is therefore only reachable
as an index.)

## Exit codes

Shared with jqlite:

| Code | Meaning |
|---|---|
| `0` | success |
| `2` | usage error — a missing/empty/extra column argument or an unknown flag |
| `4` | parse error — malformed CSV on stdin |
| `5` | query error — unknown column name or out-of-range index |

A **usage error** (exit `2`) is a problem with how the command was invoked: no
column argument, an empty column argument (`""` or whitespace-only) or one with
an empty selector (a leading/trailing/doubled comma, e.g. `name,`), an unknown
flag, a `--where` flag missing its argument, or an unexpected extra positional
argument. It is detected from the command line before stdin is read, so it takes
precedence over a parse or query error in the same invocation.

## Roadmap (signed spec, later tasks)

A single `--where COLUMN OP VALUE` predicate (`== != < <= > >=`), and `--json`
output (an array of objects keyed by the selected headers). These are not in
this scaffold; the error types and exit-code scheme above are their shared
foundation.
