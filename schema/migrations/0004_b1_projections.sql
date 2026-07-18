-- 0004_b1_projections.sql — B1.6 read-only-loop projection tables.
-- Replaces the empty B0.4 proj_plan placeholder (tile 3, no feeding event) with the
-- real plan projection, and adds 5 new B1 projections. Each indexed on correlation_id.
-- NOTE: proj_assumptions uses a plain INTEGER PRIMARY KEY (rowid alias), NOT
-- AUTOINCREMENT: a full-DELETE rebuild restarts rowids at 1, so a from-scratch replay
-- reproduces the incremental surrogate ids (Invariant 8 parity). AUTOINCREMENT keeps a
-- high-water mark across DELETE and would diverge.

DROP TABLE proj_plan;

CREATE TABLE proj_questions (
    correlation_id     TEXT,
    research_id        TEXT,
    question_id        TEXT PRIMARY KEY,
    question_text      TEXT,
    asked_at_millis    INTEGER,
    answered           INTEGER NOT NULL DEFAULT 0,
    answer_text        TEXT,
    answered_at_millis INTEGER
);
CREATE INDEX idx_proj_questions_correlation ON proj_questions(correlation_id);

CREATE TABLE proj_assumptions (
    correlation_id      TEXT,
    research_id         TEXT,
    assumption_row_id   INTEGER PRIMARY KEY,
    text                TEXT,
    confidence          REAL,
    low_confidence_flag INTEGER,
    flagged_at_millis   INTEGER
);
CREATE INDEX idx_proj_assumptions_correlation ON proj_assumptions(correlation_id);

CREATE TABLE proj_draft_spec (
    correlation_id    TEXT,
    artifact_id       TEXT,
    spec_id           TEXT PRIMARY KEY,
    signed            INTEGER NOT NULL DEFAULT 0,
    drafted_at_millis INTEGER
);
CREATE INDEX idx_proj_draft_spec_correlation ON proj_draft_spec(correlation_id);

CREATE TABLE proj_signed_spec (
    correlation_id   TEXT,
    artifact_id      TEXT,
    spec_id          TEXT PRIMARY KEY,
    signed_by        TEXT,
    signed_at_millis INTEGER
);
CREATE INDEX idx_proj_signed_spec_correlation ON proj_signed_spec(correlation_id);

CREATE TABLE proj_plan (
    correlation_id    TEXT,
    plan_id           TEXT PRIMARY KEY,
    spec_artifact_id  TEXT,
    task_count        INTEGER,
    drafted_at_millis INTEGER
);
CREATE INDEX idx_proj_plan_correlation ON proj_plan(correlation_id);

CREATE TABLE proj_explore_summary (
    correlation_id      TEXT,
    explore_pass_id     TEXT PRIMARY KEY,
    repo_root           TEXT,
    file_count          INTEGER,
    manifest_count      INTEGER,
    test_count          INTEGER,
    ci_count            INTEGER,
    completed_at_millis INTEGER
);
CREATE INDEX idx_proj_explore_summary_correlation ON proj_explore_summary(correlation_id);
