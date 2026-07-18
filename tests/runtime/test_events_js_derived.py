"""B5.6: the dashboard's event-dispatch list is DERIVED from the Python registry, not hand-kept.

Closes the B4.7 SSE-wiring gap structurally: events.generated.js is generated from EVENT_TYPES, and this
test fails closed on drift (a new event added to the Python registry without regenerating the artifact).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import manifest
from devharness.events.registry import EVENT_TYPES

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "dashboard" / "src" / "events.generated.js"
EVENTS_JS = ROOT / "dashboard" / "src" / "events.js"


def _generated_names():
    block = GENERATED.read_text(encoding="utf-8").split("EVENT_TYPES", 1)[1]
    return set(re.findall(r"'([a-z0-9_]+)'", block))


def test_generated_artifact_matches_registry():
    assert _generated_names() == set(EVENT_TYPES.keys())


def test_generated_artifact_is_what_the_writer_produces():
    # the committed file is exactly what `npm run generate-events` writes (deterministic regeneration)
    assert GENERATED.read_text(encoding="utf-8") == manifest.render()


def test_events_js_imports_the_generated_artifact():
    # events.js no longer hand-maintains the list — it imports the derived one
    text = EVENTS_JS.read_text(encoding="utf-8")
    assert "from './events.generated.js'" in text
    assert "const EVENT_TYPES = [" not in text  # the hardcoded list is gone


def test_drift_is_detected(tmp_path, monkeypatch):
    # synthetic drift: a stale artifact (missing a current event) must fail the match
    stale = tmp_path / "events.generated.js"
    names = list(EVENT_TYPES.keys())[:-1]  # drop one -> simulate "added an event without regenerating"
    stale.write_text("export const EVENT_TYPES = [\n" + "".join(f"  '{n}',\n" for n in names) + "];\n", encoding="utf-8")
    stale_names = set(re.findall(r"'([a-z0-9_]+)'", stale.read_text(encoding="utf-8")))
    assert stale_names != set(EVENT_TYPES.keys())  # drift detected
