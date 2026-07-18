-- 0024_candidate_review.sql — B5.4 operator-review columns on the candidate queues (§S7).
-- The candidate_reviewed event drives the review transition (review_state) and records who reviewed it
-- and when. ALTER ADD COLUMN (the queues are data-holding projections) — review-pending rows keep NULL
-- reviewed_by/reviewed_at_millis. (Renumbered the downstream B5.5 proj_memory migration to 0025.)

ALTER TABLE proj_antibody_queue ADD COLUMN reviewed_by TEXT;
ALTER TABLE proj_antibody_queue ADD COLUMN reviewed_at_millis INTEGER;

ALTER TABLE proj_gate_change_queue ADD COLUMN reviewed_by TEXT;
ALTER TABLE proj_gate_change_queue ADD COLUMN reviewed_at_millis INTEGER;
