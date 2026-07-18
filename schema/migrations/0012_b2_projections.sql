-- 0012_b2_projections.sql — B2.9 write-phase projection tables.
-- Derived from the write-phase events (Invariant 8 rebuildable). Surrogate keys are plain
-- INTEGER PRIMARY KEY (rowid alias, NO AUTOINCREMENT) so a DELETE+replay rebuild reproduces them.

CREATE TABLE proj_developer_activity (
    activity_row_id   INTEGER PRIMARY KEY,
    task_id           TEXT NOT NULL,
    event_type        TEXT NOT NULL CHECK (event_type IN (
        'task_started', 'task_dispatched', 'write_attempted', 'write_applied'
    )),
    correlation_id    TEXT NOT NULL,
    target_path       TEXT,
    action_kind       TEXT,
    predicted_success REAL,
    observed_success  INTEGER,
    event_at_millis   INTEGER NOT NULL
);
CREATE INDEX idx_proj_dev_activity_task ON proj_developer_activity(task_id);
CREATE INDEX idx_proj_dev_activity_correlation ON proj_developer_activity(correlation_id);

CREATE TABLE proj_verifier_outcomes (
    outcome_row_id   INTEGER PRIMARY KEY,
    task_id          TEXT NOT NULL,
    verifier_name    TEXT NOT NULL,
    outcome          TEXT NOT NULL CHECK (outcome IN ('pass', 'fail')),
    evidence_json    TEXT,
    correlation_id   TEXT NOT NULL,
    outcome_at_millis INTEGER NOT NULL
);
CREATE INDEX idx_proj_verifier_outcomes_task ON proj_verifier_outcomes(task_id);
CREATE INDEX idx_proj_verifier_outcomes_correlation ON proj_verifier_outcomes(correlation_id);
