// Tile manifest (C7) — the canonical list of every tile the dashboard renders.
// The C7 boot-check (check_dashboard_tile_coverage) parses this against the
// devharness-spec.md §S9 tile manifest; divergence either way fails closed.
export const TILE_MANIFEST = [
  // 5 generic projection tiles with a live event feed (tiles.js / 0002_projections.sql).
  // The 7 feedless B0 placeholders (proj_spec/proj_plan/proj_cost/proj_antibody_queue/
  // proj_gate_change_queue/proj_lock/proj_boot_parity) were superseded by named tiles and removed.
  'proj_role_state',
  'proj_task_queue',
  'proj_review',
  'proj_gate_fires',
  'proj_terminal_outcomes',
  // 6 B1 research-flow tiles
  'questions',
  'assumptions',
  'draft_spec',
  'signed_spec',
  'plans',
  'explore_summary',
  // 5 B2 write-phase tiles
  'developer_activity',
  'verifier_outcomes',
  'reviewer_certs',
  'lock_checkpoint',
  'trust_state',
  // 2 B3 maintenance/adversarial tiles
  'maintenance',
  'adversarial',
  // 3 B4 OSS-envelope visibility tiles
  'oss_intake',
  'oss_enforcement',
  'oss_branch',
  // 4 B5 learning-spine visibility tiles
  'candidate_queue',
  'antibody_library',
  'retro_activity',
  'trusted_memory',
  // OS-resource accounting (rev 0.3.32)
  'resource_health',
  // per-role LLM spend (rev 0.3.81) — cost_spent -> proj_cost, now surfaced
  'cost',
  // live invariant monitor (rev 0.3.87) — invariant_violated when a behavioral invariant breaks
  'invariant_monitor',
];
