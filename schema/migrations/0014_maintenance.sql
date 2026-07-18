-- 0014_maintenance.sql — B3.6 maintenance-loop projection.
-- One row per maintenance_tick / maintenance_action event (§S6). Plain INTEGER PK (no
-- AUTOINCREMENT) so a DELETE+replay rebuild reproduces the surrogate ids (Invariant 8).

CREATE TABLE proj_maintenance (
    maintenance_row_id INTEGER PRIMARY KEY,
    cycle_kind         TEXT NOT NULL CHECK (cycle_kind IN ('consolidate', 'prune', 'audit', 'synthesize')),
    event_kind         TEXT NOT NULL CHECK (event_kind IN ('tick', 'action')),
    action_description TEXT,
    correlation_id     TEXT NOT NULL,
    event_at_millis    INTEGER NOT NULL
);

CREATE INDEX idx_proj_maintenance_cycle ON proj_maintenance(cycle_kind);
CREATE INDEX idx_proj_maintenance_correlation ON proj_maintenance(correlation_id);
