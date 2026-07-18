"""call_class taxonomy — the single source of truth (B1.0, Invariant 14).

Every tool call is classified ``mutation`` | ``read`` | ``harness``. ``CALL_CLASSES``
is the one constant both the calibration metric (SQL ``WHERE call_class IN (...)``)
and the role prompts must derive from; Invariant 14 asserts they share it.
"""

CALL_CLASSES = frozenset({"mutation", "read", "harness"})

# Tools that change state.
_MUTATION = {
    "Write",
    "Edit",
    "NotebookEdit",
    "Bash",  # shell can write — classified conservatively as mutation
    "mcp__parallax__save",
    "mcp__parallax__forget",
    # B2.3 ACI write actions (B2.5: classified so the reviewer's no-write check is real)
    "mcp__devharness-aci__write_file",
    "mcp__devharness-aci__append_to_file",
    "mcp__devharness-aci__run_command",
}

# Tools that only observe.
_READ = {
    "Read",
    "Grep",
    "Glob",
    "mcp__parallax__research",
    "mcp__parallax__recall",
    "mcp__parallax__verify",
    "mcp__parallax__check",
    "mcp__parallax__grounded_verify",
    "mcp__parallax__elicit",
    "mcp__parallax__decide",
    "mcp__parallax__diverge",
    "mcp__parallax__unstick",
    "mcp__mcp-reasoning__reasoning_decision",
    "mcp__mcp-reasoning__reasoning_reflection",
    "mcp__mcp-reasoning__reasoning_meta",
    # B2.3 ACI read/test actions (reviewer-allowed)
    "mcp__devharness-aci__open_file",
    "mcp__devharness-aci__read_range",
    "mcp__devharness-aci__run_tests",
}

# Internal harness control.
_HARNESS = {
    "Task",
    "TodoWrite",
}


def classify(tool_name: str) -> str:
    """Return the call_class of a tool name; defaults to ``harness`` when unknown."""
    if tool_name in _MUTATION:
        return "mutation"
    if tool_name in _READ:
        return "read"
    if tool_name in _HARNESS:
        return "harness"
    return "harness"
