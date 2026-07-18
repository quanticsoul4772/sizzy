"""``run_invariant_sweep`` — run the behavioral checks over the event log and emit ``invariant_violated``
for each NEW violation, at top level (never from a projection handler — the emit would re-enter
``emit_sync`` mid-transaction and corrupt the hash chain / Inv-8 parity).

Idempotent: each violation has a stable ``dedup_key`` (invariant# + task + offending events); a repeated
sweep skips a violation whose key already appears in an ``invariant_violated`` event. The checks never key
on ``invariant_violated`` itself, so there is no feedback loop.
"""

import json
import time

from devharness.monitor.checks import Violation, all_violations


def _dedup_key(v: Violation) -> str:
    ids = ",".join(sorted(str(x) for x in v.offending_event_ids))
    # for a violation without offending event ids (chain/correlation), the detail carries the location
    tail = "" if v.offending_event_ids else v.detail[:120]
    return f"{v.invariant_number}|{v.task_id}|{ids}|{tail}"


def _existing_keys(conn) -> set:
    return {
        json.loads(p).get("dedup_key")
        for (p,) in conn.execute("SELECT payload FROM events WHERE event_type = 'invariant_violated'")
    }


def run_invariant_sweep(conn, event_bus, *, now_millis=None, include_orphans=True) -> list:
    """Sweep the log; emit ``invariant_violated`` for each newly-detected violation; return them.

    ``conn`` is a read connection (SELECT-only here); ``event_bus`` is the top-level single writer.
    ``include_orphans`` gates the Inv-10 liveness half (skipped automatically while a build holds the lock).
    """
    # now_millis follows the codebase convention: a CALLABLE (the schedulers pass `lambda: 7`); also
    # accept a bare int (the monitor's own tests) and None (live clock).
    now = now_millis() if callable(now_millis) else (now_millis if now_millis is not None else int(time.time() * 1000))
    seen = _existing_keys(conn)
    emitted = []
    for v in all_violations(conn, include_orphans=include_orphans):
        key = _dedup_key(v)
        if key in seen:
            continue
        seen.add(key)  # dedup within this sweep too (two checks could produce the same key)
        corr = v.correlation_id or "monitor"
        event_bus.emit_sync(
            "invariant_violated",
            {
                "invariant_number": v.invariant_number,
                "property": v.property,
                "dedup_key": key,
                "offending_event_ids": list(v.offending_event_ids),
                "task_id": v.task_id,
                "correlation_id": corr,
                "detail": v.detail,
                "detected_at_millis": now,
            },
            correlation_id=corr,
        )
        emitted.append(v)
    return emitted
