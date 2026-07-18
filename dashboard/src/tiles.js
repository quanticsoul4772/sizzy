// The 5 generic projection tiles that have a live event feed. The other 7 B0
// projection tiles (proj_spec/proj_plan/proj_cost/proj_antibody_queue/
// proj_gate_change_queue/proj_lock/proj_boot_parity) had no feeding event and
// were superseded by dedicated named tiles (Drafted/Signed specs, Plans,
// Candidate Queue, Lock & checkpoints, …) — removed rather than left as dead
// "no live event feed" placeholders. `eventTypes` lists the types feeding each.
export const TILES = [
  { table: 'proj_role_state', title: 'Active role & FSM state', eventTypes: ['connection_opened', 'role_transitioned'] },
  { table: 'proj_task_queue', title: 'Task queue', eventTypes: ['intent_proposed', 'checkpoint_taken'] },
  { table: 'proj_review', title: 'Diff under review', eventTypes: ['verifier_outcome'] },
  { table: 'proj_gate_fires', title: 'Gate fires', eventTypes: ['gate_fired'] },
  { table: 'proj_terminal_outcomes', title: 'Terminal outcomes', eventTypes: ['terminal_outcome'] },
];
