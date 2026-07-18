// Single shared SSE connection to the sidecar's /events/all channel, dispatched
// to per-tile subscribers by event_type. One long-lived EventSource for the whole
// dashboard — opening one per event type would exceed the browser's ~6
// connections-per-host HTTP/1.1 limit and starve the later tiles.
import { SIDECAR_ADDR } from './sidecar.js';
// B5.6: the dispatch list is DERIVED from the Python registry (events.generated.js), not hand-kept —
// this closes the B4.7 SSE-wiring gap where a new event type could be silently undelivered to tiles.
// Regenerate with `npm run generate-events`; CI fails on drift (test_events_js_derived.py).
import { EVENT_TYPES } from './events.generated.js';

const subscribers = new Map(); // event_type -> Set<callback>
const openCallbacks = new Set();
let source = null;
let opened = false;

function ensureSource() {
  if (source) return;
  source = new EventSource(`${SIDECAR_ADDR}/events/all`);
  source.onopen = () => {
    opened = true;
    for (const cb of openCallbacks) cb();
  };
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (event) => {
      const subs = subscribers.get(type);
      if (!subs) return;
      try {
        const msg = JSON.parse(event.data);
        // Stamp live events with receive-time. Replayed (backlog) events carry no real time — the
        // event store records no wall clock — so they get null and render as a "·" placeholder.
        msg.received_at = msg.replayed ? null : Date.now();
        for (const cb of subs) cb(msg);
      } catch {
        // ignore malformed frames
      }
    });
  }
}

// Format a receive-timestamp (millis) as a clock time; "·" for replayed/historical events that
// carry no real time. Shared by every tile so the timestamp column reads consistently.
export function fmtTime(millis) {
  if (!millis) return '·';
  return new Date(millis).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function subscribe(eventTypes, onMessage, onOpen) {
  ensureSource();
  if (onOpen) {
    if (opened) onOpen();
    else openCallbacks.add(onOpen);
  }
  for (const type of eventTypes) {
    if (!subscribers.has(type)) subscribers.set(type, new Set());
    subscribers.get(type).add(onMessage);
  }
  return () => {
    for (const type of eventTypes) subscribers.get(type)?.delete(onMessage);
    if (onOpen) openCallbacks.delete(onOpen);
  };
}
