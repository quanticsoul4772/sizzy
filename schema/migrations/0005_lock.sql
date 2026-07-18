-- 0005_lock.sql — B2.0 single-writer lock projection.
-- Replaces the empty B0.4 proj_lock placeholder (tile 11, no feeding event) with the
-- real lock projection: a row exists iff the write lock is held. Derived from the
-- write_lock_acquired / write_lock_released events (Invariant 8 rebuildable).
-- Plain TEXT/INTEGER keys, no AUTOINCREMENT (spec rev 0.3.6 convention).

DROP TABLE proj_lock;

CREATE TABLE proj_lock (
    lock_token        TEXT PRIMARY KEY,
    holder_role       TEXT NOT NULL,
    correlation_id    TEXT NOT NULL,
    acquired_at_millis INTEGER NOT NULL
);

CREATE INDEX idx_proj_lock_holder ON proj_lock(holder_role);
