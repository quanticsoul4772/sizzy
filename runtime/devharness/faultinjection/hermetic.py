"""``hermetic_build`` — a throwaway, dispatchable build for fault injection.

Packages, as RUNTIME code (the runtime must never import from ``tests/``), the same scaffold the
console-developer tests use (``tests/runtime/test_console_developer.py``): a temp git repo (``git
init`` + identity + ``app.py`` + a ``feature-base`` branch), an in-memory ``ConsoleApp``, a
directly-seeded signed spec, and a drafted single-``feature``-task plan. A probe then dispatches this
build with a fault injected at an existing developer seam (``write_hook`` / ``checkpoint_fn`` /
``query_fn`` / ``worktree_factory``) and the monitor sweep judges whether the harness coped.

Cleanup removes the ENTIRE ``mkdtemp`` root: the dispatch creates its worktree pool at
``<root>/.devharness-worktrees/repo/<task_id>`` (derived from ``base_path.parent``,
``console/developer.py``), so it lives inside the root — one Windows-robust ``rmtree`` of the root
removes the repo AND the pool. The in-memory store needs no file cleanup; its connection is closed.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from devharness.console.app import ConsoleApp
from devharness.mcp.base import CallResult
from devharness.mcp.mcp_reasoning import MCPReasoningClient
from devharness.task_classes.builtin import register_builtin_task_classes

# the worktree "test suite": passes iff app.py declares foo() returning 42 (mirrors the test scaffold)
TEST_CMD = ["python", "-c", "import sys; sys.exit(0 if 'return 42' in open('app.py').read() else 1)"]
_SUPPORTED = "Verdict: **supported** (confidence 1.0, 3/3 passes agree, no refuting findings)."


class FakeParallax:
    """A parallax client whose ``verify`` returns the rendered ``supported`` verdict — no network."""

    def __init__(self, verdict=_SUPPORTED):
        self._verdict = verdict
        self.total_cost_usd = 0.0

    async def verify(self, claim, context=""):
        return CallResult(output=self._verdict, cost_usd=0.0, usage=None, is_error=False)


def noop_query():
    """An empty async generator — the mocked coding-worker SDK query (no messages, no cost)."""

    async def query(*, prompt, options):
        if False:
            yield None

    return query


class _R:
    total_cost_usd = 0.0
    result = "ok"
    usage = {"input_tokens": 1, "output_tokens": 1}
    is_error = False


def _reasoning():
    async def query(*, prompt, options):
        yield _R()

    return MCPReasoningClient(query_fn=query)


def clean_write_hook(editor, shell, test_runner):
    """The successful worker: writes the scope-bounded change that makes ``TEST_CMD`` pass."""
    editor.write_file("app.py", "def foo():\n    return 42\n", predicted_success=0.9)
    editor.write_file("tests/test_app.py", "def test_foo():\n    assert True\n", predicted_success=0.9)


def _rmtree_robust(root: str) -> None:
    """Remove ``root`` on Windows despite read-only git objects; best-effort (never raises)."""
    for _ in range(3):
        try:
            shutil.rmtree(root)
            return
        except (PermissionError, OSError):
            for dirpath, dirnames, filenames in os.walk(root):
                for name in dirnames + filenames:
                    try:
                        os.chmod(os.path.join(dirpath, name), stat.S_IWRITE)
                    except OSError:
                        pass
    shutil.rmtree(root, ignore_errors=True)


@dataclass
class HermeticBuild:
    app: ConsoleApp
    repo: Path
    correlation_id: str
    task_id: str
    _root: str

    @property
    def conn(self):
        return self.app.conn

    @property
    def writer(self):
        return self.app.writer

    def developer(self, *, test_command=None):
        return self.app.developer(base_path=str(self.repo), test_command=test_command or TEST_CMD)

    def cleanup(self) -> None:
        try:
            self.app.conn.close()
        except Exception:  # noqa: BLE001
            pass
        _rmtree_robust(self._root)


def _git(repo: Path, *args) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def hermetic_build(*, correlation_id="fault-probe", now_millis=None) -> HermeticBuild:
    """Build a throwaway, dispatchable ``feature`` build in a temp repo + in-memory store.

    Returns a ``HermeticBuild``; the caller dispatches through ``.developer().dispatch(...)`` with a
    probe's fault injected via ``developer_kwargs`` and MUST call ``.cleanup()`` (finally)."""
    register_builtin_task_classes()  # idempotent; makes the `feature` class resolve
    root = tempfile.mkdtemp(prefix="devh-fault-")
    repo = Path(root) / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "core.fsmonitor", "false")  # standing operational invariant (no daemon leak)
    (repo / "app.py").write_text("def foo():\n    return 0\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "branch", "feature-base")

    app = ConsoleApp(db_path=":memory:").connect()
    now = now_millis() if callable(now_millis) else (now_millis if now_millis is not None else int(time.time() * 1000))
    # a directly-seeded signed spec (mirrors the test scaffold's _seed_spec — an empty payload is
    # sufficient for a feature: the spec-criteria axis reads success_criteria, absent here).
    app.conn.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, schema_version, payload_json, "
        "correlation_id, created_at_millis, signed) VALUES (?, 'spec', 1, '{}', ?, ?, 1)",
        ("fault-spec", correlation_id, now),
    )
    app.conn.commit()
    task = {
        "task_class": "feature",
        "description": "foo() returns 42",
        "scope_boundary": ["app.py", "tests/test_app.py"],
        "dependencies": [],
    }
    plan_id = app.director().plan(correlation_id, spec_id="fault-spec", tasks=[task], reasoning=_reasoning())
    row = app.conn.execute("SELECT payload_json FROM artifacts WHERE artifact_id = ?", (plan_id,)).fetchone()
    task_id = json.loads(row[0])["tasks"][0]["task_id"]
    return HermeticBuild(app=app, repo=repo, correlation_id=correlation_id, task_id=task_id, _root=root)
