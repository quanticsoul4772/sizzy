"""B1.2: C4 — the role's spawn requires harness-built context (conn) and rejects
model/operator-supplied raw context."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.roles.research import ResearchRole


def test_research_role_passes():
    assert boot.check_handoff_context_assembled_by_harness(roles=[ResearchRole]) is True


def test_rejects_raw_context_param():
    class RawContextRole:  # not an AgentRole subclass, to avoid __subclasses__ pollution
        @classmethod
        def spawn(cls, *, conn, raw_context):
            ...

        @classmethod
        def assemble_context(cls, conn, correlation_id):
            return {}

    with pytest.raises(boot.BootError):
        boot.check_handoff_context_assembled_by_harness(roles=[RawContextRole])


def test_rejects_spawn_without_conn():
    class NoConnRole:
        @classmethod
        def spawn(cls, *, idea):
            ...

        @classmethod
        def assemble_context(cls, conn, correlation_id):
            return {}

    with pytest.raises(boot.BootError):
        boot.check_handoff_context_assembled_by_harness(roles=[NoConnRole])
