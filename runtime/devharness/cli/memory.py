"""`devharness memory export|import` — operator-driven federated-memory sync (B5.5, §S7).

  devharness memory export <output_path>   # write this project's memory artifact
  devharness memory import <artifact_path>  # replay another project's artifact (entries land untrusted)

Verified-before-trusted (Inv 17) is structural: imported entries are verified_locally=0 until an
explicit verify. setting_sources=[]; no LLM in the path.
"""

import argparse
import os

from devharness.memory.export_import import export_memory, import_memory


def _conn():
    from devharness.cli._bus import open_store
    return open_store()


def main(argv=None) -> int:
    import sys

    from devharness.cli._bus import projected_bus

    parser = argparse.ArgumentParser(prog="devharness memory")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("output_path")
    im = sub.add_parser("import")
    im.add_argument("artifact_path")

    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    conn = _conn()
    try:
        if args.cmd == "export":
            n = export_memory(args.output_path, conn)
            sys.stdout.write(f"exported {n} memory entries to {args.output_path}\n")
        else:  # import
            n = import_memory(args.artifact_path, conn, projected_bus(conn))
            sys.stdout.write(f"imported {n} memory entries (untrusted until verified)\n")
    except Exception as exc:  # noqa: BLE001 — surface the failure to the operator
        sys.stderr.write(f"refused: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
