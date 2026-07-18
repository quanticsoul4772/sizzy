-- 0023_antibody_library.sql — B5.2 antibody library (§S7, Inv 11). Renumbered from 0022 (B5.1 took 0022).
-- The promoted text-only corpus (distinct from the candidate queue). pattern_text is the ONLY
-- non-metadata column — there is NO callable/code/eval column (antibodies are text only, Inv 11), and a
-- CHECK enforces non-empty pattern_text. Plain INTEGER PK (no AUTOINCREMENT); the antibody_added event
-- carries the explicit antibody_row_id so a DELETE+replay rebuild reproduces it (Invariant 8).

CREATE TABLE proj_antibody_library (
    antibody_row_id     INTEGER PRIMARY KEY,
    pattern_text        TEXT NOT NULL CHECK (length(pattern_text) > 0),
    source_candidate_id TEXT NOT NULL,
    added_by            TEXT NOT NULL,
    added_at_millis     INTEGER NOT NULL,
    revoked_at_millis   INTEGER,
    revoke_reason       TEXT,
    correlation_id      TEXT NOT NULL
);

CREATE INDEX idx_proj_antibody_library_source ON proj_antibody_library(source_candidate_id);
CREATE INDEX idx_proj_antibody_library_revoked ON proj_antibody_library(revoked_at_millis);
