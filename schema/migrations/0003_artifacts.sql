-- 0003_artifacts.sql — B1.1 handoff-artifact storage.
-- Validated handoff documents (spec, plan, verdict) stored as JSON payloads.

CREATE TABLE artifacts (
    artifact_id       TEXT PRIMARY KEY,
    artifact_type     TEXT NOT NULL,
    schema_version    INTEGER NOT NULL DEFAULT 1,
    payload_json      TEXT NOT NULL,
    correlation_id    TEXT NOT NULL,
    created_at_millis INTEGER NOT NULL,
    signed            INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_artifacts_type ON artifacts(artifact_type);
CREATE INDEX idx_artifacts_correlation ON artifacts(correlation_id);
