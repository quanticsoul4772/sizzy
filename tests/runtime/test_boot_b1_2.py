"""B1.2: the two graduated C4/C10 boot-checks pass and fail closed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.roles import base
from devharness.roles.research import ResearchRole


def test_both_registered_under_c4_and_c10():
    names = boot.registered_check_names()
    assert "check_handoff_context_assembled_by_harness" in names
    assert "check_tool_call_required_for_progress" in names
    assert boot.REQUIRED_GATES["check_handoff_context_assembled_by_harness"] == "C4"
    assert boot.REQUIRED_GATES["check_tool_call_required_for_progress"] == "C10"


def test_c4_passes_for_research_role():
    assert boot.check_handoff_context_assembled_by_harness(roles=[ResearchRole]) is True


def test_c4_fails_closed_on_raw_context():
    class Bad:
        @classmethod
        def spawn(cls, *, raw_context):
            ...

        @classmethod
        def assemble_context(cls, conn, correlation_id):
            return {}

    with pytest.raises(boot.BootError):
        boot.check_handoff_context_assembled_by_harness(roles=[Bad])


def test_c10_passes():
    assert boot.check_tool_call_required_for_progress() is True


def test_c10_fails_closed_when_metric_broken(monkeypatch):
    # a metric that counts everything (incl. text) must fail the check
    monkeypatch.setattr(base, "progress_from_messages", lambda messages: 99)
    with pytest.raises(boot.BootError):
        boot.check_tool_call_required_for_progress()
