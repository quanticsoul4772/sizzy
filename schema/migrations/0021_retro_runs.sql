-- 0021_retro_runs.sql — B5.0 retro-trigger projection (§S7 learning spine).
-- One row per retro_run event: a terminal outcome the retro auditor has processed. Doubles as the
-- dedup ledger for the event-log-derived terminal queue (a terminal whose source_task_id has no row
-- here is unprocessed). Plain INTEGER PK (no AUTOINCREMENT) so a DELETE+replay rebuild reproduces the
-- surrogate ids (Invariant 8).

CREATE TABLE proj_retro_runs (
    retro_row_id                   INTEGER PRIMARY KEY,
    terminal_outcome_correlation_id TEXT NOT NULL,
    source_task_id                 TEXT NOT NULL,
    terminal_kind                  TEXT NOT NULL CHECK (terminal_kind IN ('completed', 'rejected', 'aborted')),
    t0_matched_signatures          TEXT,  -- JSON list
    llm_invoked                    INTEGER NOT NULL,
    candidates_emitted_count       INTEGER NOT NULL,
    candidate_kinds                TEXT,  -- JSON list
    correlation_id                 TEXT NOT NULL,
    retro_run_at_millis            INTEGER NOT NULL
);

CREATE INDEX idx_proj_retro_runs_terminal_corr ON proj_retro_runs(terminal_outcome_correlation_id);
CREATE INDEX idx_proj_retro_runs_task ON proj_retro_runs(source_task_id);
CREATE INDEX idx_proj_retro_runs_kind ON proj_retro_runs(terminal_kind);
