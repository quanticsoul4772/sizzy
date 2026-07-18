-- 0008_reviewer_certs.sql — B2.5 reviewer-certification projection.
-- One row per reviewer verdict. Derived from reviewer_certified / reviewer_rejected
-- (Invariant 8 rebuildable). cert_row_id is a plain INTEGER PRIMARY KEY (rowid alias,
-- NO AUTOINCREMENT) so a DELETE+replay rebuild reproduces the surrogate ids.

CREATE TABLE proj_reviewer_certs (
    cert_row_id         INTEGER PRIMARY KEY,
    task_id             TEXT NOT NULL,
    reviewer_session_id TEXT NOT NULL,
    verdict             TEXT NOT NULL CHECK (verdict IN ('certified', 'rejected')),
    reason              TEXT,
    evidence_json       TEXT,
    correlation_id      TEXT NOT NULL,
    verdict_at_millis   INTEGER NOT NULL
);

CREATE INDEX idx_proj_reviewer_certs_task ON proj_reviewer_certs(task_id);
CREATE INDEX idx_proj_reviewer_certs_correlation ON proj_reviewer_certs(correlation_id);
