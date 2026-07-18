"""The reviewer must re-verify the feature's real claim against the realized diff, not identifiers.

A feature passed the developer's acceptance (test_suite + parallax `supported` on the diff) and was
then rejected by the reviewer, because the reviewer built its verifier claim as the bare string
"task <id> completes spec <id> per plan <id>" with no diff — parallax correctly refuses an
identifier claim with no evidence. The reviewer now forwards spec_claim + diff_content.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.roles.reviewer import ReviewerRole
from devharness.verifier.base import VerifierOk
from devharness.verifier.registry import FALSIFIERS


class _RecordingVerifier:
    def __init__(self):
        self.ctx = None

    async def verify(self, context):
        self.ctx = context
        return VerifierOk(name="feature_spec_claim", evidence={})


class _FakeBus:
    def __init__(self):
        self.events = []

    def emit_sync(self, event_type, payload, correlation_id=None):
        self.events.append(event_type)


def test_reviewer_forwards_spec_claim_and_diff_not_identifiers(monkeypatch):
    rec = _RecordingVerifier()
    monkeypatch.setitem(FALSIFIERS, "feature_spec_claim", rec)
    bus = _FakeBus()
    reviewer = ReviewerRole(
        parallax=object(), event_bus=bus, conn=None, fresh_context=True,
        verifiers=["feature_spec_claim"],
        context={
            "spec_claim": "add a --list-checks flag to the specledger CLI",
            "diff_content": "+def list_checks():\n+    return CHECK_NAMES",
            "test_command": ["pytest"], "cwd": "/wt",
        },
    )
    certified = asyncio.run(reviewer.run("t0", "spec-abc", "plan-xyz", "corr"))

    assert certified is True
    assert "reviewer_certified" in bus.events
    # the reviewer verified the real claim + realized diff, not the identifier string
    assert rec.ctx["spec_claim"] == "add a --list-checks flag to the specledger CLI"
    assert "list_checks" in rec.ctx["diff_content"]
    assert "completes spec" not in rec.ctx["claim"]


def test_reviewer_falls_back_to_identifier_claim_without_spec_claim(monkeypatch):
    # a task with no claim (e.g. scaffold) keeps the prior identifier claim — no regression
    rec = _RecordingVerifier()
    monkeypatch.setitem(FALSIFIERS, "feature_spec_claim", rec)
    reviewer = ReviewerRole(
        parallax=object(), event_bus=_FakeBus(), conn=None, fresh_context=True,
        verifiers=["feature_spec_claim"], context={"test_command": ["pytest"], "cwd": "/wt"},
    )
    asyncio.run(reviewer.run("t0", "spec-abc", "plan-xyz", "corr"))
    assert rec.ctx["claim"] == "task t0 completes spec spec-abc per plan plan-xyz"
