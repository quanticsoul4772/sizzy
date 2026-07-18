-- 0015_adversarial.sql — B3.7 adversarial self-tester projection.
-- One row per adversarial_test_run; gate_regression_detected updates the row's regression_reason.
-- Plain INTEGER PK (no AUTOINCREMENT) so a DELETE+replay rebuild reproduces the surrogate ids.

CREATE TABLE proj_adversarial (
    adversarial_row_id INTEGER PRIMARY KEY,
    probe_name         TEXT NOT NULL,
    target_gate        TEXT NOT NULL,
    outcome            TEXT NOT NULL CHECK (outcome IN ('expected_deny', 'regression_allow')),
    regression_reason  TEXT,
    correlation_id     TEXT NOT NULL,
    run_at_millis      INTEGER NOT NULL
);

CREATE INDEX idx_proj_adversarial_gate ON proj_adversarial(target_gate);
CREATE INDEX idx_proj_adversarial_outcome ON proj_adversarial(outcome);
CREATE INDEX idx_proj_adversarial_correlation ON proj_adversarial(correlation_id);
