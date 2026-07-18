"""Operator console assemble: merge every completed task's branch into the target's main, with guards.

assemble closes the loop — the per-task ``devharness/<task_id>`` branches that a build leaves in the
target repo are merged into its main in dependency order, so the operator never drops to manual git, even
for a fan-out/parallel plan. Guards: refuse an internal devharness build, refuse until every task is
completed, raise MergeConflict (abort + surface, no partial merge left behind) on a genuine content
collision. Idempotent.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console.app import ConsoleApp  # noqa: E402
from devharness.console.assemble import (  # noqa: E402
    InternalBuild,
    MergeConflict,
    NotAllCompleted,
)
from devharness.console.developer import _DEVHARNESS_REPO  # noqa: E402

CID = "proj-asm"


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)


def _new_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    main = subprocess.run(["git", "-C", str(repo), "branch", "--show-current"],
                          capture_output=True, text=True).stdout.strip()
    return repo, main


def _branch(repo, tid, base):
    _git(repo, "checkout", "-q", "-b", f"devharness/{tid}", base)
    (repo / f"{tid}.txt").write_text(f"{tid}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", tid)


def _app():
    return ConsoleApp(db_path=":memory:").connect()


def _seed_plan(app, tasks):
    """tasks: list of (task_id, [deps])."""
    plan = {
        "plan_id": "plan-1", "spec_artifact_id": "spec-1", "correlation_id": CID, "created_at_millis": 100,
        "tasks": [
            {"task_id": tid, "task_class": "feature", "description": "x", "scope_boundary": [],
             "dependencies": list(deps), "correlation_id": CID}
            for tid, deps in tasks
        ],
    }
    app.conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES ('plan-1','plan',1,?,?,100,0)",
        (json.dumps(plan), CID))
    app.conn.commit()


def _complete(app, *task_ids, outcome="completed"):
    for tid in task_ids:
        app.writer.emit_sync(
            "terminal_outcome",
            {"task_id": tid, "outcome": outcome, "detail": "", "reason": "",
             "correlation_id": CID, "terminated_at_millis": 1},
            correlation_id=CID,
        )


def test_assemble_merges_final_branch_and_records(tmp_path):
    app = _app()
    repo, main = _new_repo(tmp_path)
    _branch(repo, "t0", main)
    _branch(repo, "t1", "devharness/t0")
    _branch(repo, "t2", "devharness/t1")
    _git(repo, "checkout", "-q", main)
    _seed_plan(app, [("t0", []), ("t1", ["t0"]), ("t2", ["t1"])])
    _complete(app, "t0", "t1", "t2")

    summary = app.assemble(base_path=str(repo)).assemble(CID)
    assert "assembled" in summary
    for tid in ("t0", "t1", "t2"):
        assert (repo / f"{tid}.txt").exists()  # every task's file is on main now
    events = list(app.conn.execute("SELECT payload FROM events WHERE event_type='project_assembled'"))
    assert len(events) == 1
    payload = json.loads(events[0][0])
    assert payload["final_task_id"] == "t2"
    assert payload["merged_into_branch"] == main  # the audit trail records WHERE the build landed

    # idempotent: a second assemble is a no-op and emits no second event
    second = app.assemble(base_path=str(repo)).assemble(CID)
    assert "already assembled" in second
    assert len(list(app.conn.execute(
        "SELECT 1 FROM events WHERE event_type='project_assembled'"))) == 1


def test_assemble_refuses_internal_build():
    app = _app()
    _seed_plan(app, [("t0", [])])
    _complete(app, "t0")
    with pytest.raises(InternalBuild):
        app.assemble(base_path=str(_DEVHARNESS_REPO)).assemble(CID)


def test_assemble_refuses_until_all_completed(tmp_path):
    app = _app()
    repo, main = _new_repo(tmp_path)
    _branch(repo, "t0", main)
    _branch(repo, "t1", "devharness/t0")
    _git(repo, "checkout", "-q", main)
    _seed_plan(app, [("t0", []), ("t1", ["t0"])])
    _complete(app, "t0")  # t1 not completed
    with pytest.raises(NotAllCompleted):
        app.assemble(base_path=str(repo)).assemble(CID)


def test_assemble_merges_independent_branches(tmp_path):
    app = _app()
    repo, main = _new_repo(tmp_path)
    _branch(repo, "t0", main)
    _branch(repo, "t1", main)
    _git(repo, "checkout", "-q", main)
    _seed_plan(app, [("t0", []), ("t1", [])])  # two independent tasks, neither depends on the other
    _complete(app, "t0", "t1")

    summary = app.assemble(base_path=str(repo)).assemble(CID)
    assert "assembled" in summary
    assert (repo / "t0.txt").exists() and (repo / "t1.txt").exists()


def test_assemble_refuses_when_target_head_is_a_scratch_branch(tmp_path):
    app = _app()
    repo, main = _new_repo(tmp_path)
    _branch(repo, "t0", main)
    _branch(repo, "t1", "devharness/t0")
    _git(repo, "checkout", "-q", "devharness/t0")  # HEAD on a NON-final scratch branch, not main
    _seed_plan(app, [("t0", []), ("t1", ["t0"])])
    _complete(app, "t0", "t1")
    with pytest.raises(RuntimeError, match="scratch branch"):
        app.assemble(base_path=str(repo)).assemble(CID)
    assert not list(app.conn.execute("SELECT 1 FROM events WHERE event_type='project_assembled'"))


def test_assemble_merges_task_whose_branch_is_off_the_final_chain(tmp_path):
    """t2 depends on both t0 and t1, but a task's own git branch need not reflect every declared
    dependency — here it only chains off t1, so t0's work is only reachable by merging t0's branch
    separately. The dependency-ordered merge-each brings all three in regardless of the branch's own
    base."""
    app = _app()
    repo, main = _new_repo(tmp_path)
    _branch(repo, "t0", main)             # off main
    _branch(repo, "t1", main)             # off main (NOT off t0)
    _branch(repo, "t2", "devharness/t1")  # off t1 only -> t0 is not in t2's history
    _git(repo, "checkout", "-q", main)
    _seed_plan(app, [("t0", []), ("t1", []), ("t2", ["t0", "t1"])])
    _complete(app, "t0", "t1", "t2")

    summary = app.assemble(base_path=str(repo)).assemble(CID)
    assert "assembled" in summary
    for tid in ("t0", "t1", "t2"):
        assert (repo / f"{tid}.txt").exists()


def test_assemble_reports_merge_conflict_and_leaves_no_partial_merge(tmp_path):
    app = _app()
    repo, main = _new_repo(tmp_path)
    _branch(repo, "t0", main)
    # t1 and t2 both branch off t0 and edit base.txt's same line differently -> a real conflict.
    _git(repo, "checkout", "-q", "-b", "devharness/t1", "devharness/t0")
    (repo / "base.txt").write_text("t1-edit\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "t1")
    _git(repo, "checkout", "-q", "-b", "devharness/t2", "devharness/t0")
    (repo / "base.txt").write_text("t2-edit\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "t2")
    _git(repo, "checkout", "-q", main)
    _seed_plan(app, [("t0", []), ("t1", ["t0"]), ("t2", ["t0"])])
    _complete(app, "t0", "t1", "t2")

    with pytest.raises(MergeConflict):
        app.assemble(base_path=str(repo)).assemble(CID)
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v1"], capture_output=True, text=True
    ).stdout
    assert "UU" not in status  # no unresolved-conflict entry left — the merge was aborted
    assert not list(app.conn.execute("SELECT 1 FROM events WHERE event_type='project_assembled'"))
