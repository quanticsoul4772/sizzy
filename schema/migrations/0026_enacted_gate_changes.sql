-- 0026_enacted_gate_changes.sql — gate-change enactment (§S7, B5.4 follow-up).
-- The durable, queryable record of gate-change candidates that have been APPROVED and ENACTED into the
-- running gate config — the gate-change analogue of proj_antibody_library. Closes the asymmetry where
-- approved gate-changes dead-ended at 'approved but inert'. Plain INTEGER PK (no AUTOINCREMENT); the
-- gate_change_enacted event carries the explicit enacted_row_id so a DELETE+replay rebuild reproduces it
-- (Invariant 8). A core-gate WEAKENING can never reach this table (Inv 12, enforced in enact_gate_change).

CREATE TABLE proj_enacted_gate_changes (
    enacted_row_id      INTEGER PRIMARY KEY,
    target_gate         TEXT NOT NULL,
    change_kind         TEXT NOT NULL,
    change_details_json TEXT NOT NULL,
    source_candidate_id TEXT NOT NULL,
    enacted_by          TEXT NOT NULL,
    enacted_at_millis   INTEGER NOT NULL,
    revoked_at_millis   INTEGER,
    correlation_id      TEXT NOT NULL
);

CREATE INDEX idx_proj_enacted_gate_changes_gate ON proj_enacted_gate_changes(target_gate);
CREATE INDEX idx_proj_enacted_gate_changes_revoked ON proj_enacted_gate_changes(revoked_at_millis);
