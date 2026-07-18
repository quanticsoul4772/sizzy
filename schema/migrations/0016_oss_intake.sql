-- 0016_oss_intake.sql — B4.0 OSS-contribution intake projection (§S5).
-- One row per oss_task_intake event: the external request that must be recorded before an
-- is_oss=True BUILD task can be planned. Plain INTEGER PK (no AUTOINCREMENT) so a DELETE+replay
-- rebuild reproduces the surrogate ids (Invariant 8). Intake hardening (the accept/reject decision
-- + per-check results) lands in B4.1.

CREATE TABLE proj_oss_intake (
    intake_row_id   INTEGER PRIMARY KEY,
    upstream_repo   TEXT NOT NULL,
    license_spdx    TEXT NOT NULL,
    requester_id    TEXT NOT NULL,
    target_branch   TEXT NOT NULL,
    correlation_id  TEXT NOT NULL,
    intake_at_millis INTEGER NOT NULL
);

CREATE INDEX idx_proj_oss_intake_repo ON proj_oss_intake(upstream_repo);
CREATE INDEX idx_proj_oss_intake_requester ON proj_oss_intake(requester_id);
CREATE INDEX idx_proj_oss_intake_correlation ON proj_oss_intake(correlation_id);
