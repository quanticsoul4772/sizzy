"""B4.7: the B4 tiles' subscribed event types are registered in events.js EVENT_TYPES.

The Playwright 28-tile re-verify caught a gap svelte-check + the C7 manifest test cannot: a tile can
render and be in TILE_MANIFEST, but if its event types are absent from the events.js dispatch list,
the SSE multiplex never routes them and the tile stays empty. This guards that wiring.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

ROOT = Path(__file__).resolve().parents[2]
# B5.6: the dispatch list moved from a hardcoded events.js array to the derived events.generated.js.
GENERATED = ROOT / "dashboard" / "src" / "events.generated.js"

# the event types the three B4 tiles subscribe to (OssIntakeTile / OssEnforcementTile / OssBranchTile)
B4_TILE_EVENT_TYPES = {
    "oss_task_intake", "intake_decision", "budget_exceeded",
    "oss_worktree_created", "commit_identity_assigned",
}


def _events_js_types():
    block = GENERATED.read_text(encoding="utf-8").split("EVENT_TYPES", 1)[1]
    return set(re.findall(r"'([a-z0-9_]+)'", block))


def test_b4_event_types_registered_for_dispatch():
    registered = _events_js_types()
    missing = B4_TILE_EVENT_TYPES - registered
    assert not missing, f"events.js EVENT_TYPES missing B4 tile event types: {missing}"
