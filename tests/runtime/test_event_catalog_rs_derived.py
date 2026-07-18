"""#H9: the sidecar's EVENT_CATALOG is DERIVED from the Python registry, not hand-frozen.

It was frozen at 7 of 49 types, which neutered the /audit/dead-events L10 audit for 42 types.
event_catalog.generated.rs is generated from EVENT_TYPES; this test fails closed on drift (in the
Python CI job, which has registry access — same pattern as test_events_js_derived.py).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import manifest
from devharness.events.registry import EVENT_TYPES

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "sidecar" / "src" / "event_catalog.generated.rs"
LIB_RS = ROOT / "sidecar" / "src" / "lib.rs"


def _generated_names():
    block = GENERATED.read_text(encoding="utf-8").split("EVENT_CATALOG", 1)[1]
    return set(re.findall(r'"([a-z0-9_]+)"', block))


def test_generated_rust_catalog_matches_registry():
    assert _generated_names() == set(EVENT_TYPES.keys())


def test_generated_rust_catalog_is_what_the_writer_produces():
    # the committed file is exactly what `python -m devharness.events.manifest` writes
    assert GENERATED.read_text(encoding="utf-8").replace("\r\n", "\n") == manifest.render_rust()


def test_lib_rs_includes_the_generated_catalog():
    text = LIB_RS.read_text(encoding="utf-8")
    assert 'include!("event_catalog.generated.rs")' in text
    assert "pub const EVENT_CATALOG: [&str; 7]" not in text  # the frozen 7-element array is gone
