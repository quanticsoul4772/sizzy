"""rev 0.3.58: bytecode-cache hygiene at the harness's git surfaces.

A worker exercising the code generates __pycache__/.pytest_cache — compiler exhaust, not writes. In a
gitignore-less target those caches tripped the realized-diff scope enforcement (a live refactor task
was rejected over .pyc files) and shipped in scratch commits (a prior drive had committed .pyc files).
purge_bytecode_caches deletes the cache TREES (never a bare .pyc outside them — that stays
scope-checked; never through a symlink — a worker could point __pycache__ at in-scope files).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.worktree.hygiene import purge_bytecode_caches


def _tree(tmp_path):
    (tmp_path / "pkg" / "__pycache__").mkdir(parents=True)
    (tmp_path / "pkg" / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"x")
    (tmp_path / "tests" / "__pycache__").mkdir(parents=True)
    (tmp_path / "tests" / "__pycache__" / "t.pyc").write_bytes(b"x")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "CACHEDIR.TAG").write_text("tag")
    (tmp_path / "pkg" / "real.py").write_text("x = 1\n")
    (tmp_path / "pkg" / "bare.pyc").write_bytes(b"payload")  # NOT in a cache dir
    return tmp_path


def test_purges_cache_trees_keeps_real_files_and_bare_pyc(tmp_path):
    _tree(tmp_path)
    assert purge_bytecode_caches(tmp_path) == 3
    assert not (tmp_path / "pkg" / "__pycache__").exists()
    assert not (tmp_path / "tests" / "__pycache__").exists()
    assert not (tmp_path / ".pytest_cache").exists()
    assert (tmp_path / "pkg" / "real.py").exists()
    # a bare .pyc OUTSIDE a cache dir is a real (suspicious) write — kept, so scope checks see it
    assert (tmp_path / "pkg" / "bare.pyc").exists()


def test_tracked_caches_are_restored_to_head_not_index(tmp_path):
    # rev 0.3.59: a repo whose caches are already TRACKED (committed by pre-fix scratch commits)
    # defeated v1 — gitignore never affects tracked files, and rm-tree'ing them made the purge
    # itself the scope violation (D entries). v2 restores tracked cache paths to HEAD, so:
    # (a) porcelain is clean after the purge, (b) a worker-modified AND EVEN STAGED poisoned
    # tracked .pyc is reverted to HEAD content (checkout HEAD --, not checkout -- which restores
    # from the index), (c) untracked cache files are still removed.
    import subprocess

    repo = tmp_path / "legacy"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init", "-q")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    cache = repo / "pkg" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "m.cpython-312.pyc").write_bytes(b"HEAD-content")
    (repo / "pkg" / "real.py").write_text("x = 1\n")
    run("add", "-A")
    run("commit", "-q", "-m", "legacy repo with committed caches")

    # the worker's test run "regenerates" the tracked cache AND stages a poisoned version
    (cache / "m.cpython-312.pyc").write_bytes(b"POISON")
    run("add", "pkg/__pycache__/m.cpython-312.pyc")
    # plus a fresh untracked cache appears
    (repo / "tests" / "__pycache__").mkdir(parents=True)
    (repo / "tests" / "__pycache__" / "t.pyc").write_bytes(b"x")

    purge_bytecode_caches(repo)

    # (b) the tracked cache file is back at HEAD content — the staged poison did not survive
    assert (cache / "m.cpython-312.pyc").read_bytes() == b"HEAD-content"
    # (c) the untracked cache tree is gone
    assert not (repo / "tests" / "__pycache__").exists()
    # (a) nothing cache-related shows as changed — the scope check sees a clean tree
    porcelain = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "-uall"],
                               capture_output=True, text=True).stdout
    assert porcelain.strip() == ""


def test_purges_untracked_rust_target_dir(tmp_path):
    # rev 0.3.98: cargo test creates target/ as exhaust exactly like pytest creates __pycache__ —
    # purged (when untracked) so a gitignore-less Rust repo isn't scope-rejected over it.
    (tmp_path / "target" / "debug").mkdir(parents=True)
    (tmp_path / "target" / "debug" / "app").write_bytes(b"binary")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}\n")  # a real source file — kept
    assert purge_bytecode_caches(tmp_path) == 1
    assert not (tmp_path / "target").exists()
    assert (tmp_path / "src" / "main.rs").exists()


def test_tracked_target_dir_and_in_scope_edit_are_left_intact(tmp_path):
    # reviewer finding: a legitimately-TRACKED dir named `target` (vendored/source) must NOT be deleted
    # or reverted — else a developer's in-scope edit under it would silently vanish before the verifier
    # reads the diff. Contrast the untracked build-output case above.
    import subprocess

    repo = tmp_path / "vendored"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init", "-q")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "target").mkdir()
    (repo / "target" / "vendored.py").write_text("VERSION = 1\n")
    run("add", "-A")
    run("commit", "-q", "-m", "repo that tracks a dir named target")

    # a developer edits the tracked file IN SCOPE (uncommitted working-tree change)
    (repo / "target" / "vendored.py").write_text("VERSION = 2\n")
    assert purge_bytecode_caches(repo) == 0  # nothing removed — the tracked target is left alone
    assert (repo / "target" / "vendored.py").read_text() == "VERSION = 2\n"  # the in-scope edit survives


def test_symlinked_cache_dir_is_skipped(tmp_path):
    # a worker could symlink __pycache__ at in-scope files to get them silently deleted pre-check
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.py").write_text("keep me\n")
    link = tmp_path / "__pycache__"
    try:
        os.symlink(victim, link, target_is_directory=True)
    except OSError:
        import pytest
        pytest.skip("symlinks unavailable (Windows without privilege)")
    purge_bytecode_caches(tmp_path)
    assert (victim / "precious.py").exists()  # never followed


def test_scope_enforcement_ignores_worker_test_run_caches(tmp_path):
    # integration: a worker whose in-worktree test run generates __pycache__ in a GITIGNORE-LESS
    # target must NOT be rejected as a scope violation — the live defect this fix closes.
    import json
    import subprocess

    from devharness.console.app import ConsoleApp

    repo = tmp_path / "proj"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init", "-q")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "app.py").write_text("def foo():\n    return 0\n")
    run("add", "-A")
    run("commit", "-q", "-m", "base")  # deliberately NO .gitignore

    app = ConsoleApp(db_path=":memory:").connect()
    app.conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES ('spec-1','spec',1,'{}','c9',100,1)")
    app.conn.commit()
    app.writer.emit_sync("spec_signed", {"spec_id": "spec-1", "signer": "op", "signed_at_millis": 1}, "c9")

    from devharness.task_classes.builtin import register_builtin_task_classes
    register_builtin_task_classes()

    class _R:
        total_cost_usd = 0.0
        result = "ok"
        usage = {"input_tokens": 1, "output_tokens": 1}
        is_error = False

    from devharness.mcp.mcp_reasoning import MCPReasoningClient

    async def _rq(*, prompt, options):
        yield _R()

    app.director().plan("c9", spec_id="spec-1",
                        tasks=[{"task_class": "feature", "description": "foo returns 42",
                                "scope_boundary": ["app.py", "tests/test_app.py"], "dependencies": []}],
                        reasoning=MCPReasoningClient(query_fn=_rq))

    from devharness.mcp.base import CallResult

    class _FakeParallax:
        async def verify(self, claim, context=""):
            return CallResult(output="Verdict: **supported** (confidence 1.0).",
                              cost_usd=0.0, usage=None, is_error=False)

    async def _noop(*, prompt, options):
        if False:
            yield None

    def write_hook(editor, shell, test_runner):
        editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)
        editor.write_file("tests/test_app.py", "def test_foo():\n    assert True\n", predicted_success=0.9)
        # simulate the worker RUNNING its tests: python writes bytecode caches into the worktree
        wt = Path(editor.worktree.path)
        (wt / "__pycache__").mkdir(exist_ok=True)
        (wt / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"x")
        (wt / "tests" / "__pycache__").mkdir(parents=True, exist_ok=True)
        (wt / "tests" / "__pycache__" / "test_app.cpython-312-pytest.pyc").write_bytes(b"x")

    test_cmd = ["python", "-c", "import sys; sys.exit(0 if 'return 42' in open('app.py').read() else 1)"]
    terminal = app.developer(base_path=str(repo), test_command=test_cmd).dispatch(
        "c9", parallax=_FakeParallax(),
        developer_kwargs={"base_path": str(repo), "query_fn": _noop, "write_hook": write_hook},
        snapshot=False,
    )
    assert terminal.outcome == "completed", terminal
    # and the scratch commit shipped no caches
    ls = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "devharness/c9-t0"],
                        capture_output=True, text=True).stdout
    assert "__pycache__" not in ls and ".pyc" not in ls