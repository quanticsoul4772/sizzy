-- 0027_work_item_queue.sql — issue-discovery loop.
-- proj_work_item_queue catalogs the candidate work items a discovery run surfaces for a target repo.
-- The operator picks one; the pick is recorded as a question_answered whose answer_text is the candidate_id
-- (no separate selection event). Plain INTEGER PK (no AUTOINCREMENT) so a DELETE+replay rebuild reproduces
-- the surrogate ids (Invariant 8). A net-new table — no placeholder to DROP.

CREATE TABLE proj_work_item_queue (
    work_item_row_id   INTEGER PRIMARY KEY,
    correlation_id     TEXT NOT NULL,
    candidate_id       TEXT NOT NULL,
    title              TEXT NOT NULL,
    description        TEXT NOT NULL,
    rationale          TEXT,
    kind               TEXT NOT NULL CHECK (kind IN ('feature', 'bugfix', 'refactor', 'test_gap', 'dependency')),
    scope_hint         TEXT,  -- JSON list of path globs
    target_repo        TEXT NOT NULL,
    source             TEXT NOT NULL CHECK (source IN ('t0', 'llm')),
    created_at_millis  INTEGER NOT NULL
);
CREATE INDEX idx_proj_work_item_queue_corr ON proj_work_item_queue(correlation_id);
CREATE INDEX idx_proj_work_item_queue_cand ON proj_work_item_queue(candidate_id);
