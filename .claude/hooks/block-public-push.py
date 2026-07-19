#!/usr/bin/env python
"""PreToolUse(Bash) hook: hard-block agent pushes to any remote except `origin`.

The public mirror (and any other non-origin remote) is OPERATOR-PUBLISHED surface. The standing
free-push approval covers `origin` (the private archive) only; an agent push to the public remote is
an outward-facing act that has happened unasked (the sizzy README incident, 2026-07-19) — memory
prose did not prevent it, so this gate does. The operator pushes to public remotes themselves, or
explicitly allows one command with DEVHARNESS_ALLOW_PUBLIC_PUSH=1 inline.

Blocks by exiting 2 with the reason on stderr (the PreToolUse block protocol).
"""
import json
import os
import re
import sys

try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)

cmd = (data.get("tool_input") or {}).get("command", "")
# a commit message that DESCRIBES a push is data, not a push (the block-node-kill precedent)
if re.search(r"\bgit\s+commit\b", cmd):
    sys.exit(0)
if "DEVHARNESS_ALLOW_PUBLIC_PUSH=1" in cmd or os.environ.get("DEVHARNESS_ALLOW_PUBLIC_PUSH") == "1":
    sys.exit(0)
# every `git push` invocation in the command must target origin (bare `git push` defaults to the
# branch upstream, which is origin on this repo's main — allowed)
for m in re.finditer(r"\bgit\s+push\b\s*([^\n;&|]*)", cmd):
    args = [a for a in m.group(1).split() if not a.startswith("-")]
    if args and args[0] != "origin":
        sys.stderr.write(
            f"BLOCKED: `git push {args[0]} ...` targets a non-origin remote. Public remotes are "
            "operator-published surface — the operator pushes there themselves. If the operator has "
            "explicitly asked for this push, prefix the command with DEVHARNESS_ALLOW_PUBLIC_PUSH=1.\n"
        )
        sys.exit(2)
sys.exit(0)
