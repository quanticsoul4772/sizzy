"""Calibrated-trust evaluation — the SC-5 decision on real telemetry (#H5).

`compute_brier_for_role` (live Brier from `write_attempted`/`write_applied`) and `grant`/`renew`/
`revoke`/`has_active_trust` all existed, but nothing ever joined them: no role computed a live Brier
and acted on it, so SC-5 was never measured against real telemetry and trust was never granted on a
real path. `evaluate_trust` is that join — measure the role's per-class Brier and grant / renew /
revoke accordingly. Driven from the maintenance window (`scripts/run_maintenance.py`).
"""

from devharness.calibration.brier import compute_brier_for_role
from devharness.calibration.promotion import grant, has_active_trust, renew, revoke
from devharness.calibration.thresholds import SC5_BRIER_THRESHOLD

# the write-classes the developer earns calibrated trust on, per (role, task_class)
DEVELOPER_TASK_CLASSES = ("new_project_scaffold", "feature", "bugfix", "refactor", "dependency_bump")


def evaluate_trust(role_name, task_class, conn, event_bus, *, granted_by="calibration",
                   threshold=SC5_BRIER_THRESHOLD, min_samples=20, now_millis=None) -> dict:
    """Measure the role's live Brier for one task class and grant/renew/revoke trust (SC-5).

    Returns ``{"brier": float|None, "action": ...}`` where action is one of:
    insufficient_samples / grant / renew / revoke / none. The decision rule is code, not a model.
    """
    brier = compute_brier_for_role(role_name, task_class, conn, min_samples=min_samples)
    if brier is None:
        return {"brier": None, "action": "insufficient_samples"}

    trusted = has_active_trust(role_name, task_class, conn, now_millis=now_millis)
    if brier <= threshold:
        if trusted:
            renew(role_name, task_class, brier, granted_by, conn, event_bus, now_millis=now_millis)
            return {"brier": brier, "action": "renew"}
        grant(role_name, task_class, brier, granted_by, conn, event_bus, now_millis=now_millis)
        return {"brier": brier, "action": "grant"}

    # Brier above the SC-5 threshold: calibration is not (or no longer) good enough
    if trusted:
        revoke(role_name, task_class, f"calibration degraded: brier {brier:.3f} > {threshold}",
               granted_by, conn, event_bus, now_millis=now_millis)
        return {"brier": brier, "action": "revoke"}
    return {"brier": brier, "action": "none"}


def evaluate_developer_trust(conn, event_bus, *, now_millis=None, min_samples=20) -> dict:
    """Evaluate calibrated trust for the developer across every write-class. {task_class: action}."""
    return {
        tc: evaluate_trust("developer", tc, conn, event_bus, now_millis=now_millis, min_samples=min_samples)["action"]
        for tc in DEVELOPER_TASK_CLASSES
    }
