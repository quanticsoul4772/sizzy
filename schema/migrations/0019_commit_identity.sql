-- 0019_commit_identity.sql — B4.5 OSS commit-identity split projection (§S5).
-- One row per commit_identity_assigned event: the distinct bot identity an OSS commit landed under.
-- Plain INTEGER PK (no AUTOINCREMENT) so a DELETE+replay rebuild reproduces the surrogate ids (Inv 8).

CREATE TABLE proj_commit_identity (
    identity_row_id   INTEGER PRIMARY KEY,
    oss_task_id       TEXT NOT NULL,
    upstream_repo     TEXT NOT NULL,
    identity_name     TEXT NOT NULL,
    identity_email    TEXT NOT NULL,
    assigned_by       TEXT NOT NULL,
    commit_sha        TEXT NOT NULL,
    correlation_id    TEXT NOT NULL,
    assigned_at_millis INTEGER NOT NULL
);

CREATE INDEX idx_proj_commit_identity_task ON proj_commit_identity(oss_task_id);
CREATE INDEX idx_proj_commit_identity_repo ON proj_commit_identity(upstream_repo);
CREATE INDEX idx_proj_commit_identity_sha ON proj_commit_identity(commit_sha);
