"""ACI editor actions (B2.3).

Structured editor tools that replace raw Edit/Write. Every write is gate-checked
against the worktree boundary and the task's scope_boundary (B2.1 scope_gate), and
emits a write_attempted (refused) or write_applied event so the projection layer can
track file changes. (write_attempted / write_applied are typed structs in the EVENT_TYPES
registry, emitted via msgspec.to_builtins like every other event.)
"""

import time
from pathlib import Path

import msgspec

from devharness.events.registry import WriteApplied, WriteAttempted
from devharness.gates.base import GateDeny
from devharness.gates.scope import ScopeGate
from devharness.worktree.isolate import is_within_worktree


class ScopeViolation(RuntimeError):
    """Raised when an editor write targets a path outside the worktree or scope_boundary."""


class EditorActions:
    def __init__(self, *, worktree, scope_boundary, event_bus, conn, correlation_id, task_id, task_class="", now_millis=None):
        self.worktree = worktree
        self.scope_boundary = list(scope_boundary)
        self.event_bus = event_bus
        self.conn = conn
        self.correlation_id = correlation_id
        self.task_id = task_id
        self.task_class = task_class  # B3.0: tags write events for per-class Brier
        self._now_millis = now_millis or (lambda: int(time.time() * 1000))

    def _full(self, rel_path: str) -> Path:
        return Path(self.worktree.path) / rel_path

    def _emit(self, event_type, struct):
        self.event_bus.emit_sync(event_type, msgspec.to_builtins(struct), correlation_id=self.correlation_id)

    def _attempted(self, rel_path, action_kind, predicted_success):
        return WriteAttempted(
            task_id=self.task_id, worktree_path=self.worktree.path, target_path=rel_path,
            action_kind=action_kind, correlation_id=self.correlation_id, attempted_at_millis=self._now_millis(),
            predicted_success=predicted_success, task_class=self.task_class,
        )

    def _applied(self, rel_path, action_kind):
        return WriteApplied(
            task_id=self.task_id, worktree_path=self.worktree.path, target_path=rel_path,
            action_kind=action_kind, correlation_id=self.correlation_id, applied_at_millis=self._now_millis(),
            observed_success=True, task_class=self.task_class,
        )

    def _guard(self, rel_path: str) -> None:
        if not is_within_worktree(self._full(rel_path), self.worktree):
            raise ScopeViolation(f"File path {rel_path} outside worktree for task {self.task_id}")
        result = ScopeGate().check(
            {"touched_paths": [rel_path], "scope_boundary": self.scope_boundary, "task_id": self.task_id}
        )
        if isinstance(result, GateDeny):
            raise ScopeViolation(result.reason)

    # --- read actions ---

    def open_file(self, rel_path: str) -> str:
        return self._full(rel_path).read_text(encoding="utf-8")

    def read_range(self, rel_path: str, start: int, end: int) -> str:
        lines = self._full(rel_path).read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[max(0, start - 1):end])

    # --- write actions (gate-checked) ---
    # B2.8: every attempt emits write_attempted (predicted_success); a successful write
    # emits write_applied (observed_success). A refused write emits write_attempted only
    # (observed = no matching write_applied) — the calibration pairing for the Brier metric.

    def write_file(self, rel_path: str, content: str, predicted_success: float = 0.5) -> None:
        self._emit("write_attempted", self._attempted(rel_path, "write_file", predicted_success))
        self._guard(rel_path)
        full = self._full(rel_path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        self._emit("write_applied", self._applied(rel_path, "write_file"))

    def append_to_file(self, rel_path: str, content: str, predicted_success: float = 0.5) -> None:
        self._emit("write_attempted", self._attempted(rel_path, "append_to_file", predicted_success))
        self._guard(rel_path)
        full = self._full(rel_path)
        full.parent.mkdir(parents=True, exist_ok=True)
        with open(full, "a", encoding="utf-8") as handle:
            handle.write(content)
        self._emit("write_applied", self._applied(rel_path, "append_to_file"))
