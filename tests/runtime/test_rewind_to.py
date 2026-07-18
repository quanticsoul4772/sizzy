"""B2.4: rewind_to restores worktree state + emits rewind_performed."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.checkpoint.base import take_checkpoint
from devharness.checkpoint.rewind import rewind_to
from devharness.events.bus import EventBus
from devharness.migrate import migrate
from devharness.worktree.isolate import create_worktree, discard_worktree


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
    run("init")
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    (repo / "README.md").write_text("hi\n")
    run("add", "-A")
    run("commit", "-m", "init")
    return repo


def test_rewind_restores_tracked_file_and_emits(tmp_path):
    repo = _git_repo(tmp_path)
    worktree = create_worktree("t1", str(repo))
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    bus = EventBus(conn)

    checkpoint = take_checkpoint("t1", worktree.path, "c", bus, conn)  # baseline (README "hi\n")
    readme = Path(worktree.path) / "README.md"
    readme.write_text("changed\n")
    assert readme.read_text() == "changed\n"

    rewind_to(checkpoint, bus, conn, now_millis=lambda: 7)
    assert readme.read_text() == "hi\n"  # restored to the checkpoint

    payload = json.loads(conn.execute("SELECT payload FROM events WHERE event_type='rewind_performed'").fetchone()[0])
    assert payload["checkpoint_id"] == checkpoint.checkpoint_id
    assert payload["git_commit_sha"] == checkpoint.git_commit_sha
    assert payload["rewound_at_millis"] == 7
    discard_worktree(worktree)
