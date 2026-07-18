"""B4.6: the reused budget_exceeded event carries the OSS budget_kind discriminator + fields.

NOTE: OQ-B4-3 resolved to REUSE the existing budget_exceeded event (not mint oss_cap_exceeded), so
EVENT_TYPES stays 39 — the OSS shape is an additive extension of the existing event, not a new type.
"""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_oss_budget_kinds_accepted():
    for kind in ("oss_wall_clock", "oss_usd", "oss_requester_cooldown"):
        e = ev.BudgetExceeded(budget_kind=kind, action_taken="abort", subject_id="t1",
                              limit_value=1.0, observed_value=2.0, exceeded_at_millis=5, correlation_id="c")
        assert e.budget_kind == kind and e.subject_id == "t1"


def test_b2x_kinds_still_valid():
    # the existing per-role budget shape continues to construct unchanged
    e = ev.BudgetExceeded(role="director", budget_kind="reasoning", limit=1.0, spent=2.0)
    assert e.role == "director" and e.limit == 1.0


def test_requester_revoked_requires_reason():
    ev.BudgetExceeded(budget_kind="requester_revoked", action_taken="revoke", subject_id="r1",
                      reason="abuse", exceeded_at_millis=1, correlation_id="c")
    with pytest.raises(ValueError):
        ev.BudgetExceeded(budget_kind="requester_revoked", action_taken="revoke", subject_id="r1",
                          reason="", exceeded_at_millis=1, correlation_id="c")


def test_cooldown_kinds_null_limit_observed():
    e = ev.BudgetExceeded(budget_kind="oss_requester_cooldown", action_taken="refuse", subject_id="r1",
                          exceeded_at_millis=1, correlation_id="c")
    assert e.limit_value is None and e.observed_value is None


def test_event_types_count_at_least_39():
    # reused event type — no new catalog entry (the additive-extension consequence of OQ-B4-3)
    assert "budget_exceeded" in ev.EVENT_TYPES
    assert len(ev.EVENT_TYPES) >= 39
