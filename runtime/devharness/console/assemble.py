"""Operator console assemble action — merge a built project into the target repo's main.

After a project's tasks are all built, each certified change is committed onto a per-task
``devharness/<task_id>`` scratch branch in the target repo. For a strict-sequential plan those branches
chain linearly (the final task's branch holds the whole product); for a plan with parallel/fan-out tasks
(several tasks sharing one dependency, or independent tasks) they don't — no single branch holds
everything. Either way, the operator presses ``M`` to assemble: this merges every completed task's branch
into the target's main, in dependency order, so the loop's terminal adopt step never requires a manual
``git merge``.

Guards (no silent work loss): refuse an internal devharness build (no scratch branches); refuse until every
plan task is ``completed``. Idempotent: re-assembling a fully-merged build is a no-op; a partially-merged
build (e.g. a prior run that hit a conflict partway through) resumes — git's own merge is a no-op for a
branch whose tip is already an ancestor of HEAD. A genuine content conflict between two branches' work
raises ``MergeConflict`` and leaves no partial merge in progress (aborted). The console writes no event
store directly — the assembly is recorded through ``EventBus.emit_sync``.
"""

import json
import os
import subprocess
from pathlib import Path

import msgspec

from devharness.artifacts.plan import PlanArtifact
from devharness.console.developer import _DEVHARNESS_REPO
from devharness.events.registry import ProjectAssembled


class NoPlan(RuntimeError):
    """No plan artifact for the correlation."""


class InternalBuild(RuntimeError):
    """An internal devharness build has no scratch branches to assemble."""


class NotAllCompleted(RuntimeError):
    """Not every plan task has reached a 'completed' terminal."""


class MergeConflict(RuntimeError):
    """A task branch's work collides with another's — git can't auto-merge; resolve manually."""


class ConsoleAssemble:
    def __init__(self, conn, writer, *, base_path=None):
        self._conn = conn
        self._writer = writer  # an EventBus — emit_sync is the only sanctioned write path
        # Resolve the target exactly like ConsoleDeveloper (so an env-set target works without T).
        self._base_path = Path(base_path or os.environ.get("DEVHARNESS_TARGET_REPO") or str(_DEVHARNESS_REPO))

    def assemble(self, correlation_id) -> str:
        target = self._base_path
        if target.resolve() == _DEVHARNESS_REPO:
            raise InternalBuild("an internal devharness build has no scratch branches to assemble")
        plan_id, plan = self._resolve_plan(correlation_id)
        tasks = plan.tasks
        if not tasks:
            raise NoPlan(f"plan {plan_id!r} has no tasks to assemble")

        # All tasks must be COMPLETED (a rejected task is terminal but not completed).
        completed = self._completed_task_ids()
        not_done = [t.task_id for t in tasks if t.task_id not in completed]
        if not_done:
            raise NotAllCompleted(
                f"{len(not_done)} of {len(tasks)} task(s) not completed — finish the build first"
            )

        ordered = self._topo_order(tasks)
        branches = [f"devharness/{t.task_id}" for t in ordered]

        # Idempotent: if every task's branch is already an ancestor of HEAD, the build is assembled
        # regardless of terminal state — no re-merge, no re-emit.
        if all(self._is_ancestor(target, b, "HEAD") for b in branches):
            return f"already assembled: all {len(branches)} task branch(es) are merged into HEAD"

        # Merge into the target's current branch — capture it for the audit trail, and refuse a scratch
        # branch (assembling onto a devharness/<id> HEAD would bury the build inside the scratch chain).
        merged_into = subprocess.run(
            ["git", "-C", str(target), "branch", "--show-current"], capture_output=True, text=True
        ).stdout.strip()
        if merged_into.startswith("devharness/"):
            raise RuntimeError(
                f"target HEAD is on scratch branch {merged_into!r} — checkout the integration branch first"
            )

        # Merge every task's branch in dependency order. A branch already an ancestor of HEAD (this
        # task's work already landed via an earlier branch's history, or a resumed partial assemble) is a
        # git no-op ("Already up to date"), not an error. A real content collision aborts the in-progress
        # merge and raises — no partial merge state left behind.
        # Fallback identity for the merge COMMIT (non-fast-forward) only when the target has none
        # configured — so assemble never hits `git commit` exit 128 on a box without a global identity
        # (rev 0.3.86), without overriding the operator's identity on their own main when they have one.
        ident = ()
        for key in ("user.name", "user.email"):
            r = subprocess.run(["git", "-C", str(target), "config", key], capture_output=True, text=True)
            if r.returncode != 0 or not r.stdout.strip():
                ident = ("-c", "user.name=devharness-dev", "-c", "user.email=dev@devharness.local")
                break
        for t, branch in zip(ordered, branches):
            merge = subprocess.run(
                ["git", "-C", str(target), *ident,
                 "merge", branch, "-m", f"devharness: assemble {plan_id} ({t.task_id})"],
                capture_output=True, text=True,
            )
            if merge.returncode != 0:
                subprocess.run(["git", "-C", str(target), "merge", "--abort"], capture_output=True, text=True)
                raise MergeConflict(
                    f"task {t.task_id}'s branch ({branch}) couldn't be auto-merged — "
                    f"{(merge.stderr or merge.stdout).strip()}"
                )

        sha = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        final = ordered[-1]
        self._writer.emit_sync(
            "project_assembled",
            msgspec.to_builtins(ProjectAssembled(
                plan_id=plan_id, final_task_id=final.task_id, final_branch=f"devharness/{final.task_id}",
                merge_sha=sha, target_path=str(target), merged_into_branch=merged_into,
                correlation_id=correlation_id,
            )),
            correlation_id=correlation_id,
        )
        return f"assembled: {len(branches)} task branch(es) → {merged_into} @ {sha[:10]}"

    def _resolve_plan(self, correlation_id):
        row = self._conn.execute(
            "SELECT artifact_id, payload_json FROM artifacts "
            "WHERE artifact_type = 'plan' AND correlation_id = ? "
            "ORDER BY created_at_millis DESC, rowid DESC LIMIT 1",
            (correlation_id,),
        ).fetchone()
        if row is None:
            raise NoPlan(f"no plan for correlation_id {correlation_id!r} — plan the spec first (D)")
        return row[0], msgspec.convert(json.loads(row[1]), PlanArtifact)

    def _completed_task_ids(self) -> set:
        """Task ids whose LATEST terminal_outcome is 'completed' (one terminal per task on a clean run; a
        re-drive can append, so the latest by seq wins)."""
        latest = {}
        for task_id, outcome in self._conn.execute(
            "SELECT json_extract(payload,'$.task_id'), json_extract(payload,'$.outcome') "
            "FROM events WHERE event_type='terminal_outcome' ORDER BY seq"
        ):
            latest[task_id] = outcome
        return {tid for tid, out in latest.items() if out == "completed"}

    @staticmethod
    def _topo_order(tasks):
        """Tasks in dependency order (Kahn's algorithm), stable-tied by the plan's own task order — so a
        strict-sequential plan merges in exactly its chain order, and a fan-out merges its scaffold first."""
        by_id = {t.task_id: t for t in tasks}
        original_index = {t.task_id: i for i, t in enumerate(tasks)}
        indegree = {t.task_id: 0 for t in tasks}
        children = {t.task_id: [] for t in tasks}
        for t in tasks:
            for dep in t.dependencies:
                if dep in by_id:
                    children[dep].append(t.task_id)
                    indegree[t.task_id] += 1
        ready = sorted((tid for tid, d in indegree.items() if d == 0), key=original_index.get)
        result = []
        while ready:
            tid = ready.pop(0)
            result.append(tid)
            newly_ready = []
            for child in children[tid]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    newly_ready.append(child)
            ready = sorted(ready + newly_ready, key=original_index.get)
        if len(result) != len(tasks):
            raise NoPlan("plan's task dependencies contain a cycle — can't order the merge")
        return [by_id[tid] for tid in result]

    @staticmethod
    def _is_ancestor(target, maybe_ancestor, descendant) -> bool:
        return subprocess.run(
            ["git", "-C", str(target), "merge-base", "--is-ancestor", maybe_ancestor, descendant],
            capture_output=True, text=True,
        ).returncode == 0
