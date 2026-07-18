-- 0006_task_started.sql — B2.3 developer task-start projection.
-- One row per task the developer started (its isolated worktree path). Derived from
-- the task_started event (Invariant 8 rebuildable). Plain keys, no AUTOINCREMENT
-- (spec rev 0.3.6 convention).

CREATE TABLE proj_task_started (
    task_id          TEXT PRIMARY KEY,
    role             TEXT NOT NULL,
    worktree_path    TEXT NOT NULL,
    correlation_id   TEXT NOT NULL,
    started_at_millis INTEGER NOT NULL
);

CREATE INDEX idx_proj_task_started_correlation ON proj_task_started(correlation_id);
