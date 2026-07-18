"""Track 3: per-class blast-radius cap ratification from realized write_applied telemetry.

Few samples -> insufficient_samples (no tightening on noise); enough samples -> an evidence-based cap of
ceil(observed_max * headroom), flagged tighten/loosen/ok vs the current cap.
"""

import sqlite3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.projections.handlers import register_handlers
from devharness.projections.registry import ProjectionRegistry
from devharness.task_classes.builtin import register_builtin_task_classes
from devharness.task_classes.ratify import emit_cap_recommendations, format_report, ratify_blast_radius_caps


def _bus():
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    reg = ProjectionRegistry()
    register_handlers(reg)
    return conn, EventBus(conn, reg)


def _emit_writes(bus, writes):
    for cls, tid, path in writes:
        bus.emit_sync("write_applied", {
            "task_class": cls, "task_id": tid, "target_path": path, "action_kind": "write_file",
            "applied_at_millis": 1, "observed_success": True, "worktree_path": "w", "correlation_id": "c",
            "schema_version": 1}, correlation_id="c")


def test_insufficient_samples_reported():
    conn, bus = _bus()
    _emit_writes(bus, [("feature", "t1", "a.py"), ("feature", "t1", "b.py"), ("feature", "t2", "c.py")])
    rep = ratify_blast_radius_caps(conn, {"feature": 30}, min_samples=20)
    assert rep["feature"]["action"] == "insufficient_samples"
    assert rep["feature"]["samples"] == 2          # 2 distinct tasks (t1, t2)
    assert rep["feature"]["observed_max"] == 2      # t1 touched 2 distinct files
    assert rep["feature"]["recommended_cap"] is None  # no tightening on noise
    assert rep["feature"]["current_cap"] == 30


def test_ratifies_and_flags_tighten_when_enough_samples():
    conn, bus = _bus()
    writes = [("bugfix", f"t{i}", f"f{i}.py") for i in range(20)]  # 20 single-file tasks
    writes += [("bugfix", "tbig", p) for p in ("w.py", "x.py", "y.py", "z.py")]  # one 4-file task
    _emit_writes(bus, writes)
    rep = ratify_blast_radius_caps(conn, {"bugfix": 10}, min_samples=20, headroom=1.5)
    assert rep["bugfix"]["samples"] == 21
    assert rep["bugfix"]["observed_max"] == 4
    assert rep["bugfix"]["recommended_cap"] == 6   # ceil(4 * 1.5)
    assert rep["bugfix"]["action"] == "tighten"    # 6 < 10
    assert "bugfix" in format_report(rep)


def test_classes_with_no_telemetry_are_insufficient():
    conn, bus = _bus()
    rep = ratify_blast_radius_caps(conn, {c: 1 for c in
                                          ("new_project_scaffold", "feature", "bugfix", "refactor", "dependency_bump")})
    assert all(r["action"] == "insufficient_samples" and r["samples"] == 0 for r in rep.values())


def test_emit_recommendation_when_a_class_crosses_threshold():
    conn, bus = _bus()
    register_builtin_task_classes()  # so current_blast_radius_caps() sees bugfix=10
    # 20 single-file bugfix tasks + one 4-file task -> recommend ceil(4*1.5)=6, tighten from 10
    writes = [("bugfix", f"t{i}", f"f{i}.py") for i in range(20)]
    writes += [("bugfix", "tbig", p) for p in ("w.py", "x.py", "y.py", "z.py")]
    _emit_writes(bus, writes)

    recs = emit_cap_recommendations(conn, bus, now_millis=lambda: 1)
    bug = [r for r in recs if r["task_class"] == "bugfix"]
    assert bug and bug[0]["recommended_cap"] == 6 and bug[0]["action"] == "tighten"
    row = conn.execute("SELECT payload FROM events WHERE event_type='cap_ratification_recommended'").fetchone()
    assert row and json.loads(row[0])["task_class"] == "bugfix" and json.loads(row[0])["recommended_cap"] == 6

    # dedup: a second pass with the same telemetry re-emits nothing for bugfix
    recs2 = emit_cap_recommendations(conn, bus, now_millis=lambda: 2)
    assert all(r["task_class"] != "bugfix" for r in recs2)
    n = conn.execute("SELECT COUNT(*) FROM events WHERE event_type='cap_ratification_recommended'").fetchone()[0]
    assert n == 1  # not re-emitted


def test_no_recommendation_when_telemetry_insufficient():
    conn, bus = _bus()
    register_builtin_task_classes()
    _emit_writes(bus, [("feature", "t1", "a.py")])  # 1 sample, well below min_samples
    assert emit_cap_recommendations(conn, bus, now_millis=lambda: 1) == []
    assert conn.execute("SELECT COUNT(*) FROM events WHERE event_type='cap_ratification_recommended'").fetchone()[0] == 0
