"""B1.0: call_class is the single source of truth (Invariant 14)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.call_class import CALL_CLASSES, classify


def test_call_classes_is_exact_set():
    assert CALL_CLASSES == frozenset({"mutation", "read", "harness"})


def test_classify_known_tools():
    assert classify("Write") == "mutation"
    assert classify("Edit") == "mutation"
    assert classify("Bash") == "mutation"
    assert classify("mcp__parallax__save") == "mutation"
    assert classify("Read") == "read"
    assert classify("Grep") == "read"
    assert classify("mcp__parallax__research") == "read"
    assert classify("mcp__mcp-reasoning__reasoning_decision") == "read"
    assert classify("Task") == "harness"


def test_classify_always_returns_a_member():
    for tool in ("Write", "Read", "Task", "SomethingUnknown", ""):
        assert classify(tool) in CALL_CLASSES
