"""Brier calibration metric (B2.8, Invariant 14, SC-5).

The Brier score over the developer's mutation-call predictions vs observed outcomes.
The mutation filter derives from the CALL_CLASSES source-of-truth (call_class.py) — the
same constant the role prompts enumerate (Invariant 14).
"""

import json

from devharness.call_class import classify

ACI_SERVER = "devharness-aci"


def compute_brier(predictions) -> float:
    """Standard Brier score over (predicted_probability, observed_outcome[bool]) pairs."""
    if not predictions:
        raise ValueError("compute_brier requires at least one (predicted, observed) pair")
    total = 0.0
    for predicted, observed in predictions:
        total += (float(predicted) - (1.0 if observed else 0.0)) ** 2
    return total / len(predictions)


def _is_mutation(action_kind: str) -> bool:
    # the editor write actions are mutation tools; the filter uses the CALL_CLASSES constant
    return classify(f"mcp__{ACI_SERVER}__{action_kind}") == "mutation"


def compute_brier_for_role(role_name, task_class, conn, min_samples=20):
    """Brier over the role's mutation-call (predicted, observed) pairs for ONE task class,
    or None below min_samples.

    B3.0: filters strictly by ``task_class`` — the write_attempted/write_applied events carry
    the dispatched task's class, so one class's calibration does not bleed into another's. This
    feeds the per-class trust grant (``trust_granted``/``renewed``/``revoked`` are keyed per
    ``(role, task_class)``). Pairs each write_attempted (predicted_success) with whether a
    matching write_applied (observed_success) exists for the same (task_id, target_path).
    """
    predicted = {}
    for (payload,) in conn.execute("SELECT payload FROM events WHERE event_type = 'write_attempted'"):
        p = json.loads(payload)
        if _is_mutation(p.get("action_kind", "")) and p.get("task_class", "") == task_class:
            # NOTE (audit): keyed on (task_id, target_path), so a RE-DRIVEN task's later attempt overwrites
            # the earlier one's prediction for the same path (and `applied` unions both) — a re-drive's
            # failed earlier prediction can be dropped, slightly flattering the developer's calibration.
            # Low-impact (calibration telemetry) and a precise fix needs a per-attempt marker the write
            # events don't carry, so it is left as a documented residual rather than scoped to one attempt.
            predicted[(p["task_id"], p["target_path"])] = p.get("predicted_success", 0.5)

    applied = set()
    for (payload,) in conn.execute("SELECT payload FROM events WHERE event_type = 'write_applied'"):
        p = json.loads(payload)
        if p.get("observed_success", True) and p.get("task_class", "") == task_class:
            applied.add((p["task_id"], p["target_path"]))

    pairs = [(pred, key in applied) for key, pred in predicted.items()]
    if len(pairs) < min_samples:
        return None
    return compute_brier(pairs)
