-- 0020_oss_caps_cooldowns.sql — B4.6 OSS per-task caps + requester cooldowns/revocation (§S5).
-- proj_budget_exceeded is a normal event projection (rebuilt from budget_exceeded events, OSS kinds).
-- proj_requester_cooldown is DIRECT-WRITTEN runtime state (by check_intake_rate / revoke_requester) —
-- it is NOT registered as a rebuildable projection (excluded from the Invariant-8 parity rebuild); the
-- budget_exceeded event carries the audit trail of each cooldown/revocation trigger. Plain INTEGER PKs
-- (no AUTOINCREMENT) so a DELETE+replay rebuild reproduces the projection surrogate ids (Inv 8).

CREATE TABLE proj_requester_cooldown (
    cooldown_row_id      INTEGER PRIMARY KEY,
    requester_id         TEXT NOT NULL,
    cooldown_until_millis INTEGER NOT NULL,
    triggered_by         TEXT NOT NULL CHECK (triggered_by IN ('rate_limit', 'revocation')),
    trigger_reason       TEXT,
    correlation_id       TEXT NOT NULL,
    triggered_at_millis  INTEGER NOT NULL
);

CREATE INDEX idx_proj_requester_cooldown_requester ON proj_requester_cooldown(requester_id);
CREATE INDEX idx_proj_requester_cooldown_until ON proj_requester_cooldown(cooldown_until_millis);

CREATE TABLE proj_budget_exceeded (
    budget_row_id      INTEGER PRIMARY KEY,
    budget_kind        TEXT NOT NULL CHECK (budget_kind IN ('oss_wall_clock', 'oss_usd', 'oss_requester_cooldown', 'requester_revoked')),
    limit_value        REAL,
    observed_value     REAL,
    action_taken       TEXT NOT NULL CHECK (action_taken IN ('abort', 'refuse', 'revoke')),
    subject_id         TEXT NOT NULL,
    reason             TEXT,
    correlation_id     TEXT NOT NULL,
    exceeded_at_millis INTEGER NOT NULL
);

CREATE INDEX idx_proj_budget_exceeded_kind ON proj_budget_exceeded(budget_kind);
CREATE INDEX idx_proj_budget_exceeded_subject ON proj_budget_exceeded(subject_id);
