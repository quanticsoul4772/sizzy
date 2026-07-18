-- 0013_b3_dispatch.sql — B3.0 strict-sequential multi-task dispatch + per-class calibration.
-- proj_plan gains the in-flight task pointer; proj_plan_tasks tracks per-task terminal state so
-- a plan completes only when ALL its tasks terminate. proj_developer_activity carries task_class
-- for per-class Brier. proj_review (the B0.5 verifier stand-in) is DROPPED — superseded by
-- proj_verifier_outcomes (B2.9), which is the canonical verifier-outcome landing point; the
-- spec-named "diff under review" dashboard tile renders from the SSE stream (table-independent),
-- so dropping the table does not remove the operator surface. Plain INTEGER keys, no AUTOINCREMENT.

ALTER TABLE proj_plan ADD COLUMN current_task_id TEXT;
ALTER TABLE proj_developer_activity ADD COLUMN task_class TEXT;

CREATE TABLE proj_plan_tasks (
    plan_id             TEXT NOT NULL,
    task_id             TEXT PRIMARY KEY,
    task_state          TEXT NOT NULL CHECK (task_state IN ('pending', 'running', 'completed', 'rejected', 'aborted')),
    task_class          TEXT,
    dependency_task_ids TEXT,
    completed_at_millis INTEGER
);
CREATE INDEX idx_proj_plan_tasks_plan ON proj_plan_tasks(plan_id);
CREATE INDEX idx_proj_plan_tasks_state ON proj_plan_tasks(task_state);

DROP TABLE proj_review;
