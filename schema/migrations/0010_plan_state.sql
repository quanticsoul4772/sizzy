-- 0010_plan_state.sql — B2.7 plan execution state + task-dispatch projection.
-- proj_plan is data-holding by now (B1.6 real plan projection), so it is ALTERed in
-- place (spec rev 0.3.6 convention) rather than DROP+CREATEd. Plain keys, no AUTOINCREMENT.

ALTER TABLE proj_plan ADD COLUMN current_state TEXT NOT NULL DEFAULT 'planned'
    CHECK (current_state IN ('planned', 'executing', 'completed', 'blocked'));
ALTER TABLE proj_plan ADD COLUMN executing_task_id TEXT;
ALTER TABLE proj_plan ADD COLUMN last_terminal_at_millis INTEGER;

CREATE TABLE proj_task_dispatched (
    task_id            TEXT PRIMARY KEY,
    plan_id            TEXT NOT NULL,
    dispatched_to_role TEXT NOT NULL,
    dispatched_by_role TEXT NOT NULL,
    correlation_id     TEXT NOT NULL,
    dispatched_at_millis INTEGER NOT NULL
);

CREATE INDEX idx_proj_task_dispatched_plan ON proj_task_dispatched(plan_id);
CREATE INDEX idx_proj_task_dispatched_correlation ON proj_task_dispatched(correlation_id);
