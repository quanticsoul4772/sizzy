"""rev 0.3.61: the wrong-target contamination guard.

A stale re-entered build target once landed an entire build in ANOTHER project's repo (a wrong-target project
incident), discovered only at assemble time. The guard's signal: scratch branches
(``devharness/{cid}-t{n}``) whose embedded correlation this per-project event store has never seen —
same-store successive builds into one repo (a legitimate same-store pattern) stay silent. Warning
only, never a block.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.console.app import ConsoleApp
from devharness.worktree.contamination import foreign_scratch_correlations


def _repo(tmp_path, *branches):
    repo = tmp_path / "target"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init", "-q")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    run("commit", "--allow-empty", "-q", "-m", "init")
    for b in branches:
        run("branch", b)
    return repo


def _app():
    return ConsoleApp(db_path=":memory:").connect()


def test_unknown_correlation_branch_is_reported(tmp_path):
    repo = _repo(tmp_path, "devharness/foreign-cid-t0", "devharness/foreign-cid-t3")
    app = _app()  # fresh store: never saw foreign-cid
    assert foreign_scratch_correlations(app.conn, repo) == ["foreign-cid"]


def test_known_correlation_stays_silent(tmp_path):
    # the legitimate pattern: successive correlations building the same repo from the SAME store
    repo = _repo(tmp_path, "devharness/proj-a-t0")
    app = _app()
    app.writer.emit_sync("research_started", {"question": "q", "asked_by": "op",
                                              "asked_at_millis": 1}, correlation_id="proj-a")
    assert foreign_scratch_correlations(app.conn, repo) == []


def test_non_git_dir_is_silent(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert foreign_scratch_correlations(_app().conn, plain) == []


def test_non_task_branches_are_ignored(tmp_path):
    # only {cid}-t{n} shapes carry a recoverable correlation; devharness-oss/* is a different
    # entry surface (upstream clones, not the T build target) and the glob never matches it
    repo = _repo(tmp_path, "devharness/junk", "devharness-oss/other-cid-t0", "feature/x")
    assert foreign_scratch_correlations(_app().conn, repo) == []


def test_cid_that_itself_ends_in_tN_is_recovered(tmp_path):
    # greedy match: devharness/run-t2-t0 -> correlation "run-t2", task t0
    repo = _repo(tmp_path, "devharness/run-t2-t0")
    assert foreign_scratch_correlations(_app().conn, repo) == ["run-t2"]


async def test_set_target_warns_on_a_foreign_repo(tmp_path):
    import pytest

    pytest.importorskip("textual")  # the optional [tui] extra — absent on the CI matrix
    from devharness.console.tui import ConsoleTUI

    class _EmptyConsumer:
        def frames(self):
            return iter(())

    repo = _repo(tmp_path, "devharness/other-project-t1")
    app = _app()
    tui = ConsoleTUI(console=app, consumer_factory=_EmptyConsumer)
    logged: list[str] = []
    async with tui.run_test():
        tui._log = logged.append
        tui._set_target(str(repo))
        assert tui._target_path == str(repo)  # warning only — the target still sets
    assert any("never seen" in m and "other-project" in m for m in logged)
