"""`devharness init` — write the advisory-lite MCP config and print the next steps (rev 0.4.29).

The one-command version of the wiring hand-built for the charfreq drive: an ``mcp.local.json``
carrying both bundled advisory-lite server entries with THIS interpreter's absolute path, then the
exact env lines and console launch a fresh user needs. The advisory bootstrap, not a config
manager — users with real MCP servers edit the written ``command``/``args`` per
docs/local-mcp-setup.md.

Postures (each review-shaped): the file is produced by ``json.dump`` (string templating would break
on Windows backslashes); an existing file is a ``refused:``/exit-1, never a silent overwrite
(``--force``); a missing ``--path`` parent fails closed naming it (the open_store precedent — no
silent mkdir); the write is SELF-VALIDATED through ``mcp.config.server_cfg`` (the single config
source — the parity guard bans re-reading the JSON here) with the env override saved/restored in
``try/finally`` so an in-process caller's environment is never mutated; the never-commit warning
keys on ACTUAL gitignore status (``git check-ignore`` — the bare pattern matches at any repo depth,
so a location-based warning would be false inside subdirectories); a pre-set
``DEVHARNESS_MCP_CONFIG`` pointing elsewhere is called out (never silently redirect an operator
with real servers wired). No persistent env writing — session-scoped shell lines only.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from devharness.mcp.config import MCPConfigError, server_cfg


def _advisory_config() -> dict:
    exe = sys.executable
    return {
        "mcpServers": {
            "parallax": {"command": exe, "args": ["-m", "devharness.advisory", "--tools", "parallax"]},
            "mcp-reasoning": {"command": exe, "args": ["-m", "devharness.advisory", "--tools", "reasoning"]},
        }
    }


def _self_validate(path: Path) -> None:
    """Resolve both entries through the single config source against the just-written file.
    Env override saved/restored so an in-process caller (the tests dispatch main() directly)
    never keeps the mutation."""
    prior = os.environ.get("DEVHARNESS_MCP_CONFIG")
    os.environ["DEVHARNESS_MCP_CONFIG"] = str(path)
    try:
        server_cfg("parallax")
        server_cfg("mcp-reasoning")
    finally:
        if prior is None:
            os.environ.pop("DEVHARNESS_MCP_CONFIG", None)
        else:
            os.environ["DEVHARNESS_MCP_CONFIG"] = prior


def _gitignored(path: Path) -> bool:
    try:
        r = subprocess.run(["git", "check-ignore", "-q", path.name],
                           cwd=str(path.parent), capture_output=True)
        return r.returncode == 0
    except OSError:
        return False  # no git available -> treat as not ignored (the warning errs safe)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="devharness init",
                                     description="Write the advisory-lite MCP config and print next steps.")
    parser.add_argument("--path", default="mcp.local.json",
                        help="target file (default: ./mcp.local.json)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args(argv)

    path = Path(args.path).resolve()
    if path.exists() and not args.force:
        print(f"refused: {path} exists (use --force to overwrite)", file=sys.stderr)
        return 1
    if not path.parent.is_dir():
        print(f"refused: parent directory does not exist: {path.parent}", file=sys.stderr)
        return 1

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_advisory_config(), fh, indent=2)
        fh.write("\n")
    try:
        _self_validate(path)
    except MCPConfigError as exc:
        print(f"refused: the written config did not validate: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {path}")
    print("  both MCP servers point at the bundled advisory-lite substitute")
    print("  (real parallax/mcp-reasoning servers? edit command/args — see docs/local-mcp-setup.md)")
    print()
    prior = os.environ.get("DEVHARNESS_MCP_CONFIG")
    if prior and Path(prior).resolve() != path:
        print(f"NOTE: DEVHARNESS_MCP_CONFIG is currently set to {prior}")
        print("      the new file takes effect only when you re-point it (lines below)")
        print()
    if not _gitignored(path):
        print("WARNING: this file is not gitignored here — never commit it; it may later carry keys")
        print()
    print("Next steps — set the env in YOUR shell, then launch the console:")
    print()
    print("  # PowerShell")
    print(f'  $env:DEVHARNESS_MCP_CONFIG = "{path}"')
    print('  $env:DEVHARNESS_DB = "var/myproject.db"   # per-project event store')
    print("  python -m devharness.console")
    print()
    print("  # bash / zsh")
    print(f'  export DEVHARNESS_MCP_CONFIG="{path}"')
    print('  export DEVHARNESS_DB="var/myproject.db"')
    print("  python -m devharness.console")
    print()
    print("Walkthrough of your first build: docs/first-build.md")
    return 0
