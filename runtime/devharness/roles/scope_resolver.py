"""Dispatch-time scope widener — the files a task's change must ALSO touch.

The director sets `scope_boundary` from spec prose with zero repo grounding, so it can be too narrow: a
struct-field change needs the struct's definition file + every construction/test site, but if those aren't in
scope the worker (which physically cannot edit out-of-scope files) leaves a half-changed crate that won't
compile. This runs a read-only Agent SDK session (the discovery posture: Read/Grep/Glob only, no write/exec,
setting_sources=[]) against the dispatched task's WORKTREE — where a dependency's files already exist, unlike
HEAD at plan time — and returns the extra repo-relative files the change must edit. WIDEN-ONLY: the caller
unions these onto the model's scope; this never removes a glob, so it can never box the worker (worst case []).
"""

import json
import os

import claude_agent_sdk as sdk

from devharness.models import default_model

_READ_TOOLS = ["Read", "Grep", "Glob"]
_DISALLOWED_WRITE_EXEC = ["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit"]


def _prompt(task) -> str:
    claim = getattr(task, "spec_claim", "") or ""
    return (
        "You are analyzing the repository at the current working directory — READ-ONLY, do not modify "
        "anything. A code change is about to be made for this task:\n\n"
        f"Task: {task.description}\n"
        + (f"Verified claim the change must satisfy: {claim}\n" if claim else "")
        + f"Files already in the change's scope: {list(task.scope_boundary)}\n\n"
        "Using Read/Grep/Glob, find every OTHER repo-relative file this change MUST also edit to compile and "
        "pass tests but that is NOT already in the scope list above — the definition site of each symbol the "
        "change touches AND every construction/use/test site (e.g. adding a field to a struct requires editing "
        "the struct's definition file and EVERY file that constructs it, including test files, plus any "
        "module/import declaration). Be thorough: a missing file makes the build fail.\n\n"
        'Return ONLY a JSON array of repo-relative path strings (exact paths, no globs, no prose); [] if none.'
    )


def _extract_json_array(text: str) -> str:
    s, e = text.find("["), text.rfind("]")
    return text[s : e + 1] if s != -1 and e > s else text


def _validate(text: str, worktree_path: str, task) -> list[str]:
    """Keep only well-formed, repo-relative paths that actually EXIST in the worktree and aren't already in
    scope — drop hallucinated paths, absolute paths, and `..` escapes."""
    try:
        data = json.loads(_extract_json_array(text or ""))
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    existing = set(task.scope_boundary)
    out: list[str] = []
    for p in data:
        if not isinstance(p, str) or not p.strip():
            continue
        rel = p.strip().replace("\\", "/")
        if rel.startswith("/") or ".." in rel.split("/"):
            continue
        if not os.path.exists(os.path.join(worktree_path, rel)):
            continue
        if rel in existing or rel in out:
            continue
        out.append(rel)
    return out


async def resolve_extra_scope(worktree_path, task, *, query_fn=None, model=None,
                              mcp_server_configs=None, cost_sink=None) -> list[str]:
    """The repo-relative files this task's change must ALSO edit (beyond its declared scope). Read-only; the
    caller unions the result onto scope_boundary. Returns [] on any malformed/empty model output (no-op).

    ``cost_sink(amount_usd)`` receives the session's realized cost when > 0 — the role stays SDK-only
    (no bus here); the caller owns the ``cost_spent`` emission and its task attribution (SC-6)."""
    query_fn = query_fn or sdk.query
    options = sdk.ClaudeAgentOptions(
        setting_sources=[], mcp_servers=dict(mcp_server_configs or {}), cwd=str(worktree_path),
        model=model or default_model(), allowed_tools=_READ_TOOLS, disallowed_tools=_DISALLOWED_WRITE_EXEC,
        permission_mode="bypassPermissions",
    )
    from devharness.sdk_query import run_query  # overage auth-fallback (rev 0.4.0)
    result = None
    async for message in run_query(query_fn, _prompt(task), options):
        if getattr(message, "total_cost_usd", None) is not None:
            result = message
    if cost_sink is not None:
        cost = float(getattr(result, "total_cost_usd", 0) or 0)
        if cost > 0:
            cost_sink(cost)
    text = getattr(result, "result", "") if result is not None else ""
    return _validate(text, str(worktree_path), task)
