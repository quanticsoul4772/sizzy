"""B2.8: trust events exist with declared fields; EVENT_TYPES is 30."""

import sys
from pathlib import Path

import msgspec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_trust_events_registered():
    for name in ("trust_granted", "trust_renewed", "trust_revoked"):
        assert name in ev.EVENT_TYPES
    g = msgspec.convert({"role_name": "developer", "task_class": "new_project_scaffold", "brier_at_grant": 0.1, "granted_at_millis": 1, "expires_at_millis": 2, "granted_by": "operator", "correlation_id": "c"}, ev.TrustGranted)
    assert g.brier_at_grant == 0.1
    r = msgspec.convert({"role_name": "developer", "task_class": "c", "brier_at_renewal": 0.08, "renewed_at_millis": 1, "new_expires_at_millis": 9, "renewed_by": "operator", "correlation_id": "c"}, ev.TrustRenewed)
    assert r.new_expires_at_millis == 9


def test_trust_revoked_reason_non_empty_at_construction():
    ev.TrustRevoked(role_name="developer", task_class="c", reason="x", revoked_at_millis=1, revoked_by="op", correlation_id="c")
    with pytest.raises(ValueError):
        ev.TrustRevoked(role_name="developer", task_class="c", reason="", revoked_at_millis=1, revoked_by="op", correlation_id="c")


def test_event_types_count_at_least_30():
    assert len(ev.EVENT_TYPES) >= 30
