-- 0011_trust_grants.sql — B2.8 calibrated-trust projection.
-- One row per trust grant; expiry extended by renewal, ended by revocation. Derived from
-- trust_granted / trust_renewed / trust_revoked (Invariant 8 rebuildable). grant_row_id is
-- a plain INTEGER PRIMARY KEY (rowid alias, NO AUTOINCREMENT) so a DELETE+replay rebuild
-- reproduces the surrogate ids.

CREATE TABLE proj_trust_grants (
    grant_row_id      INTEGER PRIMARY KEY,
    role_name         TEXT NOT NULL,
    task_class        TEXT NOT NULL,
    brier_at_grant    REAL NOT NULL,
    granted_at_millis INTEGER NOT NULL,
    expires_at_millis INTEGER NOT NULL,
    revoked_at_millis INTEGER,
    granted_by        TEXT NOT NULL
);

CREATE INDEX idx_proj_trust_grants_role_class ON proj_trust_grants(role_name, task_class);
CREATE INDEX idx_proj_trust_grants_expires ON proj_trust_grants(expires_at_millis);
