-- 0028_signal_retro_runs.sql — the dedup ledger for the signal-retro trigger (§S7 learning-loop closure).
-- One row per signal_retro_run event: an invariant_violated / fault_handling_regression event the retro
-- auditor has processed into operator-review candidates. A signal event whose event_id has no row here is
-- unprocessed (parallels proj_retro_runs for terminals). The PK IS the signal's own event_id (TEXT, not a
-- surrogate), so a DELETE+replay rebuild reproduces it exactly (Invariant 8 parity).

CREATE TABLE proj_signal_retro_runs (
    signal_event_id          TEXT PRIMARY KEY,
    signal_event_type        TEXT NOT NULL,
    candidates_emitted_count INTEGER NOT NULL,
    candidate_kinds          TEXT,  -- JSON list
    correlation_id           TEXT NOT NULL,
    run_at_millis            INTEGER NOT NULL
);

CREATE INDEX idx_proj_signal_retro_runs_type ON proj_signal_retro_runs(signal_event_type);
