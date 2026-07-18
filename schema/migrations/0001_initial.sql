-- 0001_initial.sql — B0.1 substrate migration.
-- Ships only the append-only event log and the migration ledger.
-- Projection tables are deferred to B0.3; FTS5 + sqlite-vec memory stubs to B5.

CREATE TABLE schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE events (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,  -- monotonic
    event_id       TEXT,
    correlation_id TEXT NOT NULL,                      -- Invariant 9
    event_type     TEXT,
    payload        TEXT,                               -- JSON
    prev_hash      TEXT,
    hash           TEXT
);
