"""B4.4: OssWorktreeCreated + OssScopeBoundaryDerived exist with declared fields; EVENT_TYPES 38."""

import sys
from pathlib import Path

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.events import registry as ev


def test_oss_worktree_created_registered():
    assert "oss_worktree_created" in ev.EVENT_TYPES
    w = msgspec.convert(
        {"oss_task_id": "t1", "upstream_repo": "octo/widget", "target_branch": "main",
         "fork_branch": "devharness-oss/t1", "worktree_path": "/wt/t1", "created_at_millis": 5, "correlation_id": "c"},
        ev.OssWorktreeCreated,
    )
    assert w.fork_branch == "devharness-oss/t1" and w.target_branch == "main"


def test_oss_scope_boundary_derived_registered():
    assert "oss_scope_boundary_derived" in ev.EVENT_TYPES
    s = msgspec.convert(
        {"oss_task_id": "t1", "allowed_paths": ["src/**"], "derivation_basis": "build_class + within_worktree",
         "derived_at_millis": 6, "correlation_id": "c"},
        ev.OssScopeBoundaryDerived,
    )
    assert s.allowed_paths == ["src/**"] and "within_worktree" in s.derivation_basis


def test_event_types_count_at_least_38():
    assert len(ev.EVENT_TYPES) >= 38
