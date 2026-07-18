"""OS-resource accounting for the harness (stdlib-only, best-effort, cross-platform).

The harness tracks its own *events* rigorously but had no visibility into the OS *resources* it
consumes (processes, worktrees, memory) — which is how the fsmonitor `git fsmonitor--daemon` leak
went unnoticed until it tripped the Agent SDK's 60s init timeout. ``system_snapshot`` captures a
cheap resource reading the drivers emit as a ``resource_snapshot`` event per task, so growth shows on
the dashboard and a pre-flight check can warn before it bites. Every probe degrades to ``-1`` on any
error or unsupported platform — telemetry must never break a run.
"""

import os
import subprocess
import sys
from pathlib import Path

_GIT_LEAK_WARN = 50  # git.exe count above this signals the fsmonitor-daemon leak (normally ~0-2)


def _run(cmd) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout


def _process_count() -> int:
    try:
        if sys.platform == "win32":
            return _run(["tasklist", "/fo", "csv", "/nh"]).count("\n")
        return sum(1 for p in os.listdir("/proc") if p.isdigit())
    except Exception:
        return -1


def _git_process_count() -> int:
    """Count of git processes — the fsmonitor-daemon leak signal (each orphaned daemon is a git.exe)."""
    try:
        if sys.platform == "win32":
            return _run(["tasklist", "/fi", "imagename eq git.exe", "/fo", "csv", "/nh"]).lower().count('"git.exe"')
        out = _run(["pgrep", "-c", "git"]).strip()
        return int(out) if out.isdigit() else 0
    except Exception:
        return -1


def _free_memory_mb() -> int:
    try:
        if sys.platform == "win32":
            for line in _run(["wmic", "OS", "get", "FreePhysicalMemory", "/value"]).splitlines():
                if "FreePhysicalMemory" in line:
                    return int(line.split("=")[1].strip()) // 1024  # KB -> MB
            return -1
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024  # KB -> MB
        return -1
    except Exception:
        return -1


def _worktree_count(base_path) -> int:
    if not base_path:
        return -1
    try:
        out = _run(["git", "-C", str(Path(base_path)), "worktree", "list"])
        return len([line for line in out.splitlines() if line.strip()])
    except Exception:
        return -1


def system_snapshot(base_path=None) -> dict:
    """A cheap resource reading: total processes, git processes (leak signal), git worktrees for
    ``base_path``, and free physical memory (MB). Any failed probe is ``-1``."""
    return {
        "process_count": _process_count(),
        "git_process_count": _git_process_count(),
        "worktree_count": _worktree_count(base_path),
        "free_memory_mb": _free_memory_mb(),
    }


def leak_warning(snapshot: dict) -> str | None:
    """A human-readable warning if the snapshot looks like the fsmonitor leak, else None."""
    git = snapshot.get("git_process_count", -1)
    if git > _GIT_LEAK_WARN:
        return (f"{git} git processes running — likely orphaned fsmonitor daemons (the leak). "
                "Check `wmic process where \"name='git.exe'\" get commandline` / see CLAUDE.md.")
    return None


def emit_snapshot(event_bus, correlation_id, *, base_path=None, now_millis=None) -> dict:
    """Capture + emit a ``resource_snapshot`` event; return the snapshot. Every live driver calls this
    at start so process/worktree/memory growth shows on the dashboard for the whole loop, not just the
    developer path — the leak class that hid behind the SDK init-timeouts can grow in any driver."""
    import time

    snapshot = system_snapshot(base_path)
    at = int(time.time() * 1000) if now_millis is None else now_millis
    event_bus.emit_sync(
        "resource_snapshot",
        {**snapshot, "captured_at_millis": at, "correlation_id": correlation_id},
        correlation_id=correlation_id,
    )
    return snapshot
