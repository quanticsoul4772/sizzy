-- 0009_task_lifecycle.sql — B2.6 task-lifecycle projection.
-- One row per task: its current state + terminal outcome. Derived from task_started /
-- terminal_outcome (Invariant 8 rebuildable). The boot-check (C2) scans current_state
-- for silently-terminated tasks. Plain keys, no AUTOINCREMENT (spec rev 0.3.6).

CREATE TABLE proj_task_lifecycle (
    task_id           TEXT PRIMARY KEY,
    current_state     TEXT NOT NULL CHECK (current_state IN (
        'queued', 'running', 'awaiting_verifier', 'awaiting_review', 'completed', 'rejected', 'aborted'
    )),
    started_at_millis INTEGER,
    terminal_at_millis INTEGER,
    outcome           TEXT,
    reason            TEXT
);

CREATE INDEX idx_proj_task_lifecycle_state ON proj_task_lifecycle(current_state);
