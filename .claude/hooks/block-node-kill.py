#!/usr/bin/env python
"""PreToolUse(Bash) hook: hard-block a blanket `taskkill //IM node.exe`.

The Playwright MCP server itself runs as a node.exe process, so a blanket node kill drops the MCP
mid-task — the documented root cause of the B1.7-B5.7 dashboard-render deferrals (see CLAUDE.md). Tear the
dev stack down with `scripts/dev_stack.sh --down` (sidecar.exe by image + the vite PID *by port*) instead.

Blocks by exiting 2 with the reason on stderr (the PreToolUse block protocol).
"""
import json
import re
import sys

try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)

cmd = (data.get("tool_input") or {}).get("command", "")
# A git-commit command carries its message as data (a heredoc / -m string), not an executed kill — a
# commit message that DESCRIBES the footgun must not be blocked. (A real `taskkill` is its own command.)
if re.search(r"\bgit\s+commit\b", cmd):
    sys.exit(0)
# taskkill targeting node.exe by IMAGE — the blanket kill. Matches `/IM` and `//IM` flag forms.
if re.search(r"taskkill\b[^\n]*?/{1,2}IM\s+node(\.exe)?\b", cmd, re.IGNORECASE):
    sys.stderr.write(
        "BLOCKED: `taskkill //IM node.exe` kills the Playwright MCP server (it runs as node.exe). "
        "Tear the dev stack down with `scripts/dev_stack.sh --down` (kills sidecar.exe + the vite PID by "
        "port), never a blanket node kill. See CLAUDE.md.\n"
    )
    sys.exit(2)
sys.exit(0)
