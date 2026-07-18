"""B5.5: MemoryEntry struct + project_name helper."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.memory.base import MemoryEntry, project_name


def test_entry_frozen_kw_only():
    e = MemoryEntry(entry_id="id1", entry_type="antibody", entry_payload={"pattern_text": "x"},
                    source_project="devharness", created_at_millis=1, correlation_id="c")
    assert e.entry_type == "antibody" and e.entry_payload["pattern_text"] == "x"
    with pytest.raises(AttributeError):
        e.entry_id = "id2"
    with pytest.raises(TypeError):
        MemoryEntry("id1", "antibody", {}, "p", 1, "c")  # positional rejected


def test_roundtrip():
    e = MemoryEntry(entry_id="id1", entry_type="antibody", entry_payload={"a": 1}, source_project="p", created_at_millis=1, correlation_id="c")
    assert msgspec.convert(msgspec.to_builtins(e), MemoryEntry) == e


def test_project_name_default_and_env(monkeypatch):
    monkeypatch.delenv("DEVHARNESS_PROJECT_NAME", raising=False)
    assert project_name() == "devharness"
    monkeypatch.setenv("DEVHARNESS_PROJECT_NAME", "sibling-agent")
    assert project_name() == "sibling-agent"
