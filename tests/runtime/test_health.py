"""OS-resource accounting: system_snapshot + the resource_snapshot event.

Closes the harness's resource-accounting gap (the fsmonitor-leak class went unseen because the
harness tracked events but not the OS resources it consumed). Telemetry must never break a run, so
every probe degrades to -1 rather than raising.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

import msgspec

from devharness.events.registry import EVENT_TYPES, ResourceSnapshot
from devharness.health import leak_warning, system_snapshot


def test_system_snapshot_has_int_metrics():
    snap = system_snapshot(str(Path(__file__).resolve().parents[2]))
    assert set(snap) == {"process_count", "git_process_count", "worktree_count", "free_memory_mb"}
    assert all(isinstance(v, int) for v in snap.values())  # a real reading or -1, never a crash


def test_leak_warning_fires_above_threshold_only():
    assert leak_warning({"git_process_count": 500}) is not None  # the leak signal
    assert leak_warning({"git_process_count": 2}) is None        # normal
    assert leak_warning({"git_process_count": -1}) is None       # failed probe -> no false alarm


def test_resource_snapshot_event_registered_and_validates():
    assert EVENT_TYPES["resource_snapshot"] is ResourceSnapshot
    payload = {**system_snapshot(None), "captured_at_millis": 1, "correlation_id": "c"}
    msgspec.convert(payload, ResourceSnapshot)  # the emitted payload validates against the struct


def test_emit_snapshot_emits_a_valid_resource_snapshot():
    # the shared helper every driver calls (not just run_developer) — emits + returns the snapshot
    from devharness.health import emit_snapshot

    emitted = []

    class _Bus:
        def emit_sync(self, event_type, payload, correlation_id=None):
            emitted.append((event_type, payload, correlation_id))

    snap = emit_snapshot(_Bus(), "drv", base_path=None, now_millis=7)
    assert set(snap) == {"process_count", "git_process_count", "worktree_count", "free_memory_mb"}
    assert len(emitted) == 1
    event_type, payload, cid = emitted[0]
    assert event_type == "resource_snapshot" and cid == "drv"
    assert payload["captured_at_millis"] == 7 and payload["correlation_id"] == "drv"
    msgspec.convert(payload, ResourceSnapshot)  # the helper's payload validates against the struct
