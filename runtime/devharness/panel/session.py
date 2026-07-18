"""Per-panel target/project state — ported from the console TUI's ``T`` / ``N`` / ``P`` flows.

The build TARGET (``target_path`` + ``test_command``) and which event store is the active PROJECT are
TUI-instance state today (``console/tui.py`` ``_target_path`` / ``_set_target`` / ``_prepare_target`` /
``_discover_projects``). The panel holds the same state per session. ``set_target`` prepares the repo
on demand (create dir + ``git init`` + a first commit + disable ``core.fsmonitor``) and persists a
``build_target_set`` event through the single writer, so a restart restores it — exactly as the TUI.

Actions here that only prepare files/read are lock-free; the one write (``build_target_set``) goes
through ``PanelWriter.emit_sync`` (serialized). Switching the active store rebuilds the writer and is
owned by :mod:`devharness.panel.server` (it must be refused mid-build).
"""

import shlex
import sqlite3
import subprocess
from pathlib import Path

from devharness.worktree.contamination import foreign_scratch_correlations
from devharness.worktree.hygiene import SEEDED_GITIGNORE


class PanelSession:
    """Build-target + project state for one panel session."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.target_path: str | None = None
        self.test_command: list[str] | None = None

    # --- build target (T) ---

    def prepare_target(self, path: str, msgs: list[str]) -> str | None:
        """Make ``path`` a usable build target (git repo with a commit), creating+initing if needed.
        Returns None on success else a one-line failure reason. Ported from ``tui._prepare_target``."""
        p = Path(path)
        if not p.exists():
            try:
                p.mkdir(parents=True)
                msgs.append(f"created {path}")
            except OSError as exc:
                return f"can't create {path}: {exc}"
        if not p.is_dir():
            return f"{path} is not a directory"
        if subprocess.run(["git", "-C", path, "rev-parse", "--git-dir"],
                          capture_output=True, text=True).returncode != 0:
            r = subprocess.run(["git", "-C", path, "init", "-q"], capture_output=True, text=True)
            if r.returncode != 0:
                return f"git init failed: {r.stderr.strip()}"
            msgs.append(f"git init {path}")
            gi = Path(path) / ".gitignore"
            if not gi.exists():
                gi.write_text(SEEDED_GITIGNORE, encoding="utf-8")
                subprocess.run(["git", "-C", path, "add", ".gitignore"], capture_output=True, text=True)
                msgs.append(f"seeded .gitignore in {path}")
        if subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                          capture_output=True, text=True).returncode != 0:
            r = subprocess.run(
                ["git", "-C", path, "-c", "user.name=devharness-dev",
                 "-c", "user.email=dev@devharness.local", "commit", "--allow-empty", "-m", "init", "-q"],
                capture_output=True, text=True)
            if r.returncode != 0:
                return f"initial commit failed: {r.stderr.strip()}"
            msgs.append(f"initial commit in {path}")
        # Git-for-Windows enables core.fsmonitor system-wide; the per-worktree git churn orphans daemons
        # -> SDK init timeouts. Disable it on the target (no-op/harmless on Linux).
        subprocess.run(["git", "-C", path, "config", "core.fsmonitor", "false"],
                       capture_output=True, text=True)
        return None

    def set_target(self, value: str, writer) -> dict:
        """Set the build target from ``'<repo_path> | <test command>'``; persist ``build_target_set``.
        Returns {'ok', 'target_path', 'test_command', 'messages'}."""
        msgs: list[str] = []
        path, sep, cmd = value.partition("|")
        path = path.strip()
        if not path:
            return {"ok": False, "messages": ["target NOT set — give a repo path"]}
        problem = self.prepare_target(path, msgs)
        if problem:
            msgs.append(f"target NOT set — {problem}")
            return {"ok": False, "messages": msgs}
        self.target_path = path
        self.test_command = shlex.split(cmd.strip(), posix=False) if (sep and cmd.strip()) else None
        writer.emit_sync(
            "build_target_set",
            {"target_path": self.target_path, "test_command": self.test_command or [],
             "correlation_id": "console"},
            correlation_id="console",
        )
        cmd_note = f"  ·  test = {' '.join(self.test_command)}" if self.test_command else ""
        msgs.append(f"build target = {self.target_path}{cmd_note}")
        msgs += self._warn_foreign(path)
        return {"ok": True, "target_path": self.target_path,
                "test_command": self.test_command, "messages": msgs}

    def restore_target(self, conn: sqlite3.Connection) -> list[str]:
        """Restore the store's latest T-set target on connect. Validates the path is still a git repo
        with a HEAD — a stale path is reported, not restored (never re-created). Ported from
        ``tui._restore_target`` (the deliberate no-resurrect behaviour is preserved)."""
        row = conn.execute(
            "SELECT json_extract(payload,'$.target_path'), payload FROM events "
            "WHERE event_type='build_target_set' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if not row:
            return []
        import json
        path = row[0]
        cmd = json.loads(row[1]).get("test_command") or []
        ok = Path(path).is_dir() and subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True
        ).returncode == 0
        if not ok:
            return [f"stale build target NOT restored: {path} (missing or not a git repo) — set target"]
        self.target_path = path
        self.test_command = list(cmd) if cmd else None
        cmd_note = f"  ·  test = {' '.join(self.test_command)}" if self.test_command else ""
        return [f"restored build target = {path}{cmd_note}", *self._warn_foreign(path)]

    def _warn_foreign(self, path: str) -> list[str]:
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                foreign = foreign_scratch_correlations(conn, path)
            finally:
                conn.close()
        except sqlite3.Error:
            return []
        if foreign:
            return [f"⚠ {path} carries devharness scratch branches from correlation(s) this store has "
                    f"never seen: {', '.join(foreign)} — another project's build target? verify before build"]
        return []

    # --- project discovery (P) ---

    def discover_projects(self) -> list[dict]:
        """[{db_path, name, target}] for every ``*.db`` beside the current store — READ-ONLY (a mode=ro
        connection, so listing never migrates/locks a sibling). Ported from ``tui._discover_projects``."""
        if self.db_path in (":memory:", "", None):
            return []
        from devharness.migrate import is_event_store

        out: list[dict] = []
        for db in sorted(Path(self.db_path).parent.glob("*.db")):
            # rev 0.4.13: a foreign sqlite file (the MCP servers' own databases live in the same
            # var/ on the VPS) is not a project — offering it in the Switch dropdown invites
            # migrating devharness schema into it. Only positive not-a-store evidence omits;
            # a transiently-unreadable REAL store keeps its row (the (unreadable) label below).
            if is_event_store(db) is False:
                continue
            target = "(no target)"
            try:
                ro = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
                try:
                    row = ro.execute(
                        "SELECT json_extract(payload,'$.target_path') FROM events "
                        "WHERE event_type='build_target_set' ORDER BY seq DESC LIMIT 1"
                    ).fetchone()
                    if row and row[0]:
                        target = row[0]
                finally:
                    ro.close()
            except sqlite3.Error:
                target = "(unreadable)"
            out.append({"db_path": str(db), "name": db.stem, "target": target})
        return out
