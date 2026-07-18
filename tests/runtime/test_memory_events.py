"""B5.5: MemoryEntryCreated + MemoryEntryVerified events; EVENT_TYPES 49."""

import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_memory_entry_created_registered():
    assert "memory_entry_created" in ev.EVENT_TYPES
    e = msgspec.convert({"entry_id": "id1", "entry_type": "antibody", "entry_payload_json": "{}",
                         "source_project": "devharness", "created_at_millis": 1, "correlation_id": "c"}, ev.MemoryEntryCreated)
    assert e.entry_id == "id1" and e.source_project == "devharness"


def test_memory_entry_verified_registered():
    assert "memory_entry_verified" in ev.EVENT_TYPES
    e = msgspec.convert({"entry_id": "id1", "verifier_evidence_json": "{}", "verified_by": "op",
                         "verified_at_millis": 5, "correlation_id": "c"}, ev.MemoryEntryVerified)
    assert e.verified_by == "op"


def test_event_types_are_well_formed():
    # Structural invariant instead of a magic count (which churned on every new event): each event_type
    # maps to a msgspec.Struct, the keys are non-empty snake_case, no duplicates. Manifest drift (registry
    # vs the generated dashboard/sidecar catalogs) is guarded by test_events_js_derived / _rs_derived.
    assert len(ev.EVENT_TYPES) > 0
    for name, struct in ev.EVENT_TYPES.items():
        assert name and name.islower() and " " not in name, f"bad event_type key: {name!r}"
        assert isinstance(struct, type) and issubclass(struct, msgspec.Struct), f"{name} -> not a Struct"
