-- 0022_candidate_queues.sql — B5.1 retro CANDIDATE queues (§S7 learning spine).
-- Replaces the B0 placeholder tables (empty, no feeding handler) with the real retro candidate queues.
-- DROP+CREATE is safe per the repo convention (empty placeholders may be DROP+CREATEd; data-holding
-- tables need ALTER/CTAS). Plain INTEGER PKs (no AUTOINCREMENT) so a DELETE+replay rebuild reproduces
-- the surrogate ids (Invariant 8). review_state defaults to 'pending' — no CANDIDATE auto-applies (SC-2).

DROP TABLE proj_antibody_queue;
CREATE TABLE proj_antibody_queue (
    antibody_row_id          INTEGER PRIMARY KEY,
    retro_run_correlation_id TEXT NOT NULL,
    signature_name           TEXT,
    pattern_text             TEXT NOT NULL,
    evidence_event_ids       TEXT,  -- JSON list
    source                   TEXT NOT NULL CHECK (source IN ('t0', 'llm', 'quarantine')),
    review_state             TEXT NOT NULL DEFAULT 'pending' CHECK (review_state IN ('pending', 'approved', 'rejected')),
    created_at_millis        INTEGER NOT NULL
);
CREATE INDEX idx_proj_antibody_queue_retro ON proj_antibody_queue(retro_run_correlation_id);
CREATE INDEX idx_proj_antibody_queue_source ON proj_antibody_queue(source);
CREATE INDEX idx_proj_antibody_queue_state ON proj_antibody_queue(review_state);

DROP TABLE proj_gate_change_queue;
CREATE TABLE proj_gate_change_queue (
    gate_change_row_id       INTEGER PRIMARY KEY,
    retro_run_correlation_id TEXT NOT NULL,
    signature_name           TEXT,
    target_gate              TEXT NOT NULL,
    change_kind              TEXT NOT NULL CHECK (change_kind IN ('tighten', 'loosen', 'add_signature', 'remove_signature')),
    change_details_json      TEXT NOT NULL,
    evidence_event_ids       TEXT,  -- JSON list
    source                   TEXT NOT NULL CHECK (source IN ('t0', 'llm')),
    review_state             TEXT NOT NULL DEFAULT 'pending' CHECK (review_state IN ('pending', 'approved', 'rejected')),
    created_at_millis        INTEGER NOT NULL
);
CREATE INDEX idx_proj_gate_change_queue_retro ON proj_gate_change_queue(retro_run_correlation_id);
CREATE INDEX idx_proj_gate_change_queue_source ON proj_gate_change_queue(source);
CREATE INDEX idx_proj_gate_change_queue_state ON proj_gate_change_queue(review_state);
