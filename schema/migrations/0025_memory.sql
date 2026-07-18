-- 0025_memory.sql — B5.5 federated cross-project memory (§S7, Inv 17). Renumbered from 0024 (B5.4 took 0024).
-- Each project carries its own proj_memory. verified_locally is 0 for imported entries (untrusted) until
-- verify_memory_entry promotes them (Inv 17: verified-before-trusted); 1 for locally-created entries.
-- Plain INTEGER PK (no AUTOINCREMENT); entry_id is the stable cross-project id (UNIQUE → import idempotency).

CREATE TABLE proj_memory (
    memory_row_id         INTEGER PRIMARY KEY,
    entry_id              TEXT NOT NULL UNIQUE,
    entry_type            TEXT NOT NULL,
    entry_payload_json    TEXT NOT NULL,
    source_project        TEXT NOT NULL,
    verified_locally      INTEGER NOT NULL DEFAULT 0,
    created_at_millis     INTEGER NOT NULL,
    verified_at_millis    INTEGER,
    verifier_evidence_json TEXT,
    correlation_id        TEXT NOT NULL
);

CREATE INDEX idx_proj_memory_entry ON proj_memory(entry_id);
CREATE INDEX idx_proj_memory_source ON proj_memory(source_project);
CREATE INDEX idx_proj_memory_verified ON proj_memory(verified_locally);
