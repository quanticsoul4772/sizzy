"""B5.6: the B5 tiles' subscribed event types are in the (now derived) events dispatch list.

Same guard shape as B4.7, but the list is now DERIVED from the Python registry — so this also confirms
the 4 B5 tiles' event types reach the dispatch list automatically (no hand-wiring step to forget).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "dashboard" / "src" / "events.generated.js"

# the event types the four B5 tiles subscribe to
B5_TILE_EVENT_TYPES = {
    "antibody_candidate", "gate_change_candidate", "candidate_reviewed", "candidate_rejected",
    "gate_change_rejected", "antibody_added", "antibody_revoked", "retro_run",
    "memory_entry_created", "memory_entry_verified",
}


def _generated_types():
    block = GENERATED.read_text(encoding="utf-8").split("EVENT_TYPES", 1)[1]
    return set(re.findall(r"'([a-z0-9_]+)'", block))


def test_b5_event_types_in_dispatch_list():
    missing = B5_TILE_EVENT_TYPES - _generated_types()
    assert not missing, f"events.generated.js missing B5 tile event types: {missing}"
