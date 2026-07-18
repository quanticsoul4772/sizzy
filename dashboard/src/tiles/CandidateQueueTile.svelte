<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from '../events.js';

  // B5.6: retro CANDIDATE review queues — pending counts (antibody + gate-change) + recent reviews,
  // with the auto-rejected (B5.3 validator) vs operator-rejected distinction visible.
  let pendingAntibody = $state(0);
  let pendingGateChange = $state(0);
  let feed = $state([]); // {label, detail}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    let label = '', detail = '';
    if (msg.event_type === 'antibody_candidate') {
      pendingAntibody += 1;
      label = 'candidate:antibody';
      detail = p.signature_name || p.pattern_text || '';
    } else if (msg.event_type === 'gate_change_candidate') {
      pendingGateChange += 1;
      label = 'candidate:gate-change';
      detail = `${p.target_gate} / ${p.change_kind}`;
    } else if (msg.event_type === 'candidate_reviewed') {
      if (p.candidate_kind === 'antibody_candidate') pendingAntibody = Math.max(0, pendingAntibody - 1);
      else pendingGateChange = Math.max(0, pendingGateChange - 1);
      label = `reviewed:${p.review_state}`;
      detail = `${p.candidate_kind} by ${p.reviewed_by}`;
    } else if (msg.event_type === 'gate_change_rejected') {
      pendingGateChange = Math.max(0, pendingGateChange - 1);
      label = 'auto-rejected'; // B5.3 validator (core-gate weakening)
      detail = `${p.target_gate}: ${p.rejection_reason}`;
    } else {
      // candidate_rejected (audit trail of an operator reject)
      label = 'rejected';
      detail = `${p.candidate_kind}: ${p.reason}`;
    }
    feed = [...feed, { label, detail, received_at: msg.received_at }].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(
      ['antibody_candidate', 'gate_change_candidate', 'candidate_reviewed', 'candidate_rejected', 'gate_change_rejected'],
      apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Candidate Queue</h2>
  <small>antibody · gate_change · reviewed · rejected · auto-rejected</small>
  <p>pending: antibody {pendingAntibody} · gate-change {pendingGateChange}</p>
  {#if feed.length === 0}
    <p>no candidate queue yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each feed as e, i (i)}
        <li><span class="ts">{fmtTime(e.received_at)}</span> <span>[{e.label}]</span> {e.detail}</li>
      {/each}
    </ul>
  {/if}
</section>
