"""devharness CLI entry point (#L3).

`python -m devharness <subcommand> [args]` — and the installed `devharness` console script — dispatch
to the `cli.<subcommand>` modules. This is the `devharness <subcmd>` UX the docstrings reference;
previously only `python -m devharness.cli.<subcommand>` worked. Each cli module exposes
`main(argv) -> int`.
"""

import importlib
import sys

_SUBCOMMANDS = ("init", "answer", "sign", "retro", "memory", "ratify", "prune", "questions", "work-items", "sweep", "backfill")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(f"usage: devharness <subcommand> [args]\nsubcommands: {', '.join(_SUBCOMMANDS)}", file=sys.stderr)
        return 2
    if argv[0] in ("-h", "--help"):
        print(f"usage: devharness <subcommand> [args]\nsubcommands: {', '.join(_SUBCOMMANDS)}")
        return 0
    sub, rest = argv[0], argv[1:]
    if sub not in _SUBCOMMANDS:
        print(f"devharness: unknown subcommand {sub!r}; choose from: {', '.join(_SUBCOMMANDS)}", file=sys.stderr)
        return 2
    module = importlib.import_module(f"devharness.cli.{sub.replace('-', '_')}")
    return module.main(rest) or 0


if __name__ == "__main__":
    raise SystemExit(main())
