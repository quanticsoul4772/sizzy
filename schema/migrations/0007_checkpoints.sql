-- 0007_checkpoints.sql — B2.4 checkpoint projection.
-- One row per worktree checkpoint; rewound_at_millis is set when a rewind targets it.
-- Derived from checkpoint_taken / rewind_performed (Invariant 8 rebuildable). Plain
-- keys, no AUTOINCREMENT (spec rev 0.3.6 convention).

CREATE TABLE proj_checkpoints (
    checkpoint_id     TEXT PRIMARY KEY,
    task_id           TEXT NOT NULL,
    worktree_path     TEXT NOT NULL,
    git_commit_sha    TEXT NOT NULL,
    correlation_id    TEXT NOT NULL,
    taken_at_millis   INTEGER NOT NULL,
    rewound_at_millis INTEGER
);

CREATE INDEX idx_proj_checkpoints_task ON proj_checkpoints(task_id);
CREATE INDEX idx_proj_checkpoints_correlation ON proj_checkpoints(correlation_id);
