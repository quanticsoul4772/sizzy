"""Per-class blast-radius cap re-ratification from realized telemetry (Track 3 / the OQ3 follow-up).

The B3.1 write-class caps (`feature`/`bugfix`/`refactor`/`dependency_bump`) are PROVISIONAL — the OQ3
ratification deferred tightening them to live-workload telemetry. This computes each class's *realized*
blast radius (the distinct files a task actually wrote, from `write_applied` events) and recommends an
evidence-based cap.

It is deliberately conservative: a cap is only recommended when a class has at least ``min_samples`` tasks
of telemetry — with fewer, it reports ``insufficient_samples`` rather than tightening a cap on noise (three
single-file tasks do not bound what a real feature touches). It RECOMMENDS; applying a recommendation to
``task_classes/builtin.py`` stays a deliberate operator act (as the original OQ3 ratification was).
"""

import collections
import json
import math
import time

import msgspec

from devharness.events.registry import CapRatificationRecommended

WRITE_CLASSES = ("new_project_scaffold", "feature", "bugfix", "refactor", "dependency_bump")
DEFAULT_MIN_SAMPLES = 20
DEFAULT_HEADROOM = 1.5  # the cap must clear the largest observed task with margin for a bigger legit one


def realized_radii_by_class(conn) -> dict[str, list[int]]:
    """Map each task_class to the list of realized blast radii (distinct files written) over its tasks,
    read from ``write_applied`` events (one set of target_paths per task_id)."""
    rows = conn.execute("SELECT payload FROM events WHERE event_type='write_applied'").fetchall()
    files: dict[tuple, set] = collections.defaultdict(set)
    for (payload,) in rows:
        d = json.loads(payload)
        path = d.get("target_path")
        if path:  # don't count a missing/empty path as a distinct file (it would inflate blast radius)
            files[(d.get("task_class"), d.get("task_id"))].add(path)
    by_class: dict[str, list[int]] = collections.defaultdict(list)
    for (task_class, _task_id), paths in files.items():
        if task_class:
            by_class[task_class].append(len(paths))
    return dict(by_class)


def current_blast_radius_caps() -> dict[str, int]:
    """The registered per-class blast-radius caps (the current provisional/ratified values)."""
    from devharness.task_classes.registry import TASK_CLASSES
    return {name: spec.blast_radius_limit for name, spec in TASK_CLASSES.items()
            if name in WRITE_CLASSES and spec.blast_radius_limit is not None}


def ratify_blast_radius_caps(conn, current_caps=None, *, min_samples=DEFAULT_MIN_SAMPLES,
                             headroom=DEFAULT_HEADROOM) -> dict[str, dict]:
    """Per write-class: realized-telemetry-based cap recommendation. ``action`` is one of
    ``insufficient_samples`` | ``tighten`` | ``loosen`` | ``ok``. ``recommended_cap`` is
    ``ceil(observed_max * headroom)`` once ``samples >= min_samples``, else None."""
    current_caps = current_blast_radius_caps() if current_caps is None else current_caps
    by_class = realized_radii_by_class(conn)
    report: dict[str, dict] = {}
    for cls in WRITE_CLASSES:
        radii = sorted(by_class.get(cls, []))
        current = current_caps.get(cls)
        if len(radii) < min_samples:
            report[cls] = {"samples": len(radii), "observed_max": (radii[-1] if radii else None),
                           "current_cap": current, "recommended_cap": None, "action": "insufficient_samples"}
            continue
        observed_max = radii[-1]
        recommended = math.ceil(observed_max * headroom)
        if current is None:
            action = "set"
        elif recommended < current:
            action = "tighten"
        elif recommended > current:
            action = "loosen"
        else:
            action = "ok"
        report[cls] = {"samples": len(radii), "observed_max": observed_max, "current_cap": current,
                       "recommended_cap": recommended, "action": action}
    return report


def emit_cap_recommendations(conn, event_bus, *, min_samples=DEFAULT_MIN_SAMPLES, headroom=DEFAULT_HEADROOM,
                             now_millis=None, correlation_id="maintenance") -> list[dict]:
    """Run the ratification and emit a ``cap_ratification_recommended`` event for each write-class that has
    crossed ``min_samples`` with a real recommendation (tighten/loosen/set) — deduped against the latest
    prior recommendation for that class (re-emit only when the recommended cap changes), so the maintenance
    window does not spam the log. The recommendation is advisory: applying it to ``task_classes/builtin.py``
    stays a deliberate operator act. Returns the emitted recommendations. Run from the fermata-paced
    maintenance window so ratification fires organically as real-task telemetry accumulates (#M4)."""
    report = ratify_blast_radius_caps(conn, min_samples=min_samples, headroom=headroom)
    at = (now_millis or (lambda: int(time.time() * 1000)))()
    emitted = []
    for cls, r in report.items():
        if r["action"] in ("insufficient_samples", "ok"):
            continue
        prior = conn.execute(
            "SELECT payload FROM events WHERE event_type='cap_ratification_recommended' "
            "AND json_extract(payload,'$.task_class')=? ORDER BY rowid DESC LIMIT 1", (cls,)).fetchone()
        if prior and json.loads(prior[0]).get("recommended_cap") == r["recommended_cap"]:
            continue  # already recommended this cap for this class — don't re-spam the log
        event_bus.emit_sync(
            "cap_ratification_recommended",
            msgspec.to_builtins(CapRatificationRecommended(
                task_class=cls, samples=r["samples"], observed_max=r["observed_max"],
                current_cap=r["current_cap"], recommended_cap=r["recommended_cap"], action=r["action"],
                recommended_at_millis=at, correlation_id=correlation_id,
            )),
            correlation_id=correlation_id,
        )
        emitted.append({"task_class": cls, "recommended_cap": r["recommended_cap"], "action": r["action"],
                        "samples": r["samples"]})
    return emitted


def format_report(report: dict[str, dict]) -> str:
    lines = ["per-class blast-radius cap ratification (realized telemetry):"]
    for cls, r in report.items():
        if r["action"] == "insufficient_samples":
            lines.append(f"  {cls:<22} samples={r['samples']:<3} INSUFFICIENT (need more runs; cap stays "
                         f"{r['current_cap']}, max-seen={r['observed_max']})")
        else:
            lines.append(f"  {cls:<22} samples={r['samples']:<3} max={r['observed_max']} "
                         f"current={r['current_cap']} -> recommend {r['recommended_cap']} [{r['action'].upper()}]")
    return "\n".join(lines)
