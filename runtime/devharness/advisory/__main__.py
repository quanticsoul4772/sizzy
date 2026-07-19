"""``python -m devharness.advisory --tools parallax|reasoning`` — serve advisory-lite over stdio.

Two DEVHARNESS_MCP_CONFIG entries → two processes, same module. Stdout is the MCP protocol; this
module (and everything it imports) must never print to stdout.
"""

import argparse
import sys

from devharness.advisory import build_app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="devharness.advisory")
    parser.add_argument("--tools", required=True, choices=("parallax", "reasoning"))
    args = parser.parse_args(argv)  # argparse exits 2 on bad/missing args, 0 on --help
    build_app(args.tools).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
