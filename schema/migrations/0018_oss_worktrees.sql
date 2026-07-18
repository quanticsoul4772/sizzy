-- 0018_oss_worktrees.sql — B4.4 OSS fork-branch worktree projection (§S5).
-- One row per oss_worktree_created event: the isolated fork-branch worktree an OSS contribution
-- runs in. Plain INTEGER PK (no AUTOINCREMENT) so a DELETE+replay rebuild reproduces the surrogate
-- ids (Invariant 8). oss_scope_boundary_derived is event-log-only (no projection at B4.4).

CREATE TABLE proj_oss_worktrees (
    worktree_row_id   INTEGER PRIMARY KEY,
    oss_task_id       TEXT NOT NULL,
    upstream_repo     TEXT NOT NULL,
    target_branch     TEXT NOT NULL,
    fork_branch       TEXT NOT NULL,
    worktree_path     TEXT NOT NULL,
    correlation_id    TEXT NOT NULL,
    created_at_millis INTEGER NOT NULL
);

CREATE INDEX idx_proj_oss_worktrees_task ON proj_oss_worktrees(oss_task_id);
CREATE INDEX idx_proj_oss_worktrees_repo ON proj_oss_worktrees(upstream_repo);
