-- 0017_intake_decisions.sql — B4.1 intake-hardening decision projection (§S5).
-- One row per intake_decision event (accepted | rejected). Plain INTEGER PK (no AUTOINCREMENT)
-- so a DELETE+replay rebuild reproduces the surrogate ids (Invariant 8).

CREATE TABLE proj_intake_decisions (
    decision_row_id       INTEGER PRIMARY KEY,
    intake_correlation_id TEXT NOT NULL,
    decision              TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    rejection_reason      TEXT,
    detected_patterns     TEXT,  -- JSON-encoded list of injection pattern names
    correlation_id        TEXT NOT NULL,
    decision_at_millis    INTEGER NOT NULL
);

CREATE INDEX idx_proj_intake_decisions_intake ON proj_intake_decisions(intake_correlation_id);
CREATE INDEX idx_proj_intake_decisions_decision ON proj_intake_decisions(decision);
