---
description: Regenerate the dashboard + sidecar event catalogs from the Python EVENT_TYPES registry.
---
After an `EVENT_TYPES` change (`runtime/devharness/events/registry.py`), regenerate the derived catalogs:

1. From `runtime/`, run `python -m devharness.events.manifest` — it writes `dashboard/src/events.generated.js` and `sidecar/src/event_catalog.generated.rs`.
2. Commit those two generated files alongside the registry change.

No magic-number bumps are needed: the count tests are derived (`test_memory_events` asserts every event_type maps to a well-formed `msgspec.Struct`; the sidecar derives from `EVENT_CATALOG.len()`). CI's `test_events_js_derived` / `test_event_catalog_rs_derived` guard registry↔catalog drift, so just regenerate + commit.
